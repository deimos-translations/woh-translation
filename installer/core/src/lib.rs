//! Core of the WoH translation installer: reads a pack (manifest + patches + files), checks the game files against it,
//! installs with `.orig` backups and restores. No prompts or printing: callers pass a log callback.

mod install;
mod locate;
mod pack;

pub use install::{State, install, restore, verify};
pub use locate::{find_game, game_beside};
pub use pack::{Entry, Manifest, Pack, append_trailer};

use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::Path};

/// Lowercase hex (the sha2 0.11 digest array has no `LowerHex`).
fn hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    bytes
        .iter()
        .fold(String::with_capacity(bytes.len() * 2), |mut text, byte| {
            let _ = write!(text, "{byte:02x}");
            text
        })
}

/// Lowercase hex sha256 of a file, streamed.
pub fn sha256_file(path: &Path) -> anyhow::Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            return Ok(hex(&hasher.finalize()));
        }
        hasher.update(&buffer[..count]);
    }
}

pub fn sha256_bytes(data: &[u8]) -> String {
    hex(&Sha256::digest(data))
}
