//! Release tool: builds the pack from the pristine game folder and the build output, and appends it to the installer exe.
//! usage: woh-pack --pristine DIR --built DIR --version TEXT --installer EXE --out FILE [--exclude PATH]
//! `--exclude` leaves one file of the build folder out (a relative path, e.g. the changelog).
//! `.exe`/`.win` files become bsdiff patches against the pristine file of the same relative path; other files are stored whole.
//! Files identical to the pristine ones are left out.
use anyhow::{Context, Result, bail};
use qbsdiff::Bsdiff;
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};
use woh_patcher_core::{Entry, Manifest, Pack, append_trailer, sha256_bytes};

fn walk(dir: &Path, out: &mut Vec<PathBuf>) -> Result<()> {
    for item in fs::read_dir(dir)? {
        let path = item?.path();
        if path.is_dir() {
            walk(&path, out)?;
        } else {
            out.push(path);
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let mut options = HashMap::new();
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        options.insert(flag, args.next().context("every option needs a value")?);
    }
    let get = |name: &str| options.get(name).with_context(|| format!("missing {name}"));
    let (pristine, built) = (Path::new(get("--pristine")?), Path::new(get("--built")?));

    let mut files = Vec::new();
    walk(built, &mut files)?;
    files.sort();
    let (mut entries, mut blobs) = (Vec::new(), Vec::<Vec<u8>>::new());
    for file in files {
        let relative = file.strip_prefix(built)?.to_string_lossy().replace('\\', "/");
        if options.get("--exclude") == Some(&relative) {
            continue;
        }
        let output = fs::read(&file)?;
        let original = fs::read(pristine.join(&relative)).ok();
        if original.as_deref() == Some(&output[..]) {
            continue;
        }
        let patched = matches!(file.extension().and_then(|ext| ext.to_str()), Some("exe" | "win"));
        let (input_sha256, blob) = match (patched, original) {
            (true, Some(source)) => {
                eprintln!("{relative}: bsdiff {} -> {} bytes", source.len(), output.len());
                let mut patch = Vec::new();
                Bsdiff::new(&source, &output).compression_level(9).compare(&mut patch)?;
                eprintln!("  patch: {} bytes", patch.len());
                (Some(sha256_bytes(&source)), patch)
            }
            (true, None) => bail!("{relative} has no pristine counterpart to patch"),
            (false, _) => (None, output.clone()),
        };
        entries.push(Entry {
            path: relative,
            input_sha256,
            output_sha256: sha256_bytes(&output),
            blob_len: blob.len() as u64,
        });
        blobs.push(blob);
    }

    let manifest = Manifest {
        version: get("--version")?.clone(),
        files: entries,
    };
    let encoded = Pack::encode(&manifest, &blobs.iter().map(Vec::as_slice).collect::<Vec<_>>())?;
    eprintln!("pack: {} bytes", encoded.len());
    fs::write(get("--out")?, append_trailer(fs::read(get("--installer")?)?, &encoded))?;
    Ok(())
}
