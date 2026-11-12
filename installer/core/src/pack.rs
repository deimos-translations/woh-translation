use anyhow::{Context, Result, bail, ensure};
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
};

const MAGIC: &[u8; 8] = b"WOHPACK1";

/// One game file the pack produces. `path` is relative to the game folder, with `/` separators.
#[derive(Deserialize, Serialize)]
pub struct Entry {
    pub path: String,
    /// `Some`: the blob is a bsdiff patch for a file with this sha256. `None`: the blob is the file itself.
    pub input_sha256: Option<String>,
    pub output_sha256: String,
    pub blob_len: u64,
}

#[derive(Deserialize, Serialize)]
pub struct Manifest {
    pub version: String,
    pub files: Vec<Entry>,
}

/// Pack container, before bzip2: u32 LE manifest length, manifest JSON, blobs of all entries in manifest order.
pub struct Pack {
    pub manifest: Manifest,
    data: Vec<u8>,
    blobs_start: usize,
}

impl Pack {
    pub fn encode(manifest: &Manifest, blobs: &[&[u8]]) -> Result<Vec<u8>> {
        let json = serde_json::to_vec(manifest)?;
        let mut raw = Vec::with_capacity(4 + json.len() + blobs.iter().map(|blob| blob.len()).sum::<usize>());
        raw.extend_from_slice(&(json.len() as u32).to_le_bytes());
        raw.extend_from_slice(&json);
        for blob in blobs {
            raw.extend_from_slice(blob);
        }
        let mut encoder = bzip2::write::BzEncoder::new(Vec::new(), bzip2::Compression::best());
        encoder.write_all(&raw)?;
        Ok(encoder.finish()?)
    }

    pub fn decode(compressed: &[u8]) -> Result<Self> {
        let mut data = Vec::new();
        bzip2::read::BzDecoder::new(compressed)
            .read_to_end(&mut data)
            .context("пакет повреждён")?;
        ensure!(data.len() >= 4, "пакет обрезан");
        let json_len = u32::from_le_bytes(data[..4].try_into()?) as usize;
        ensure!(data.len() >= 4 + json_len, "пакет обрезан");
        let manifest: Manifest = serde_json::from_slice(&data[4..4 + json_len])?;
        let blobs_start = 4 + json_len;
        let total: u64 = manifest.files.iter().map(|entry| entry.blob_len).sum();
        ensure!(blobs_start as u64 + total == data.len() as u64, "пакет обрезан");
        Ok(Self {
            manifest,
            data,
            blobs_start,
        })
    }

    /// The pack appended to an installer exe (see `append_trailer`), or a bare pack file when it has no trailer.
    pub fn read(path: &Path) -> Result<Self> {
        let mut file = File::open(path).with_context(|| format!("не удаётся открыть {}", path.display()))?;
        let size = file.seek(SeekFrom::End(0))?;
        if size >= 16 {
            file.seek(SeekFrom::Start(size - 16))?;
            let mut tail = [0u8; 16];
            file.read_exact(&mut tail)?;
            if &tail[8..] == MAGIC {
                let len = u64::from_le_bytes(tail[..8].try_into()?);
                ensure!(len <= size - 16, "пакет обрезан");
                file.seek(SeekFrom::Start(size - 16 - len))?;
                let mut compressed = vec![0u8; len as usize];
                file.read_exact(&mut compressed)?;
                return Self::decode(&compressed);
            }
        }
        file.seek(SeekFrom::Start(0))?;
        let mut compressed = Vec::new();
        file.read_to_end(&mut compressed)?;
        Self::decode(&compressed)
    }

    pub fn blob(&self, index: usize) -> &[u8] {
        let start = self.blobs_start
            + self.manifest.files[..index]
                .iter()
                .map(|entry| entry.blob_len as usize)
                .sum::<usize>();
        &self.data[start..start + self.manifest.files[index].blob_len as usize]
    }
}

/// Installer exe bytes followed by the encoded pack and a 16-byte trailer (pack length, magic).
pub fn append_trailer(mut exe: Vec<u8>, encoded: &[u8]) -> Vec<u8> {
    exe.extend_from_slice(encoded);
    exe.extend_from_slice(&(encoded.len() as u64).to_le_bytes());
    exe.extend_from_slice(MAGIC);
    exe
}

/// A path from a pack must stay inside the game folder.
pub(crate) fn safe_path(root: &Path, relative: &str) -> Result<PathBuf> {
    let mut path = root.to_path_buf();
    for part in relative.split('/') {
        if part.is_empty() || part == "." || part == ".." || part.contains(['\\', ':']) {
            bail!("небезопасный путь в пакете: {relative}");
        }
        path.push(part);
    }
    Ok(path)
}
