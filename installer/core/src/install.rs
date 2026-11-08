use crate::{Entry, Pack, pack::safe_path, sha256_bytes, sha256_file};
use anyhow::{Context, Result, bail};
use qbsdiff::Bspatch;
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum State {
    /// The file is already the translated one.
    Installed,
    /// The source is the pristine file this pack patches (or the file is only written, not patched).
    Ready,
    /// The source is neither: another game version, or a modified file.
    Mismatch,
}

fn sibling(target: &Path, suffix: &str) -> PathBuf {
    let mut name = target.as_os_str().to_owned();
    name.push(suffix);
    name.into()
}

/// State of one entry; the `.orig` backup, when there is one, is the source of a patch.
fn state(entry: &Entry, target: &Path) -> Result<State> {
    if target.is_file() && sha256_file(target)? == entry.output_sha256 {
        return Ok(State::Installed);
    }
    let Some(input) = &entry.input_sha256 else {
        return Ok(State::Ready);
    };
    let orig = sibling(target, ".orig");
    let source = if orig.is_file() { &orig } else { target };
    Ok(if source.is_file() && sha256_file(source)? == *input {
        State::Ready
    } else {
        State::Mismatch
    })
}

/// The state of every file of the pack in the game folder; nothing is written.
pub fn verify(pack: &Pack, game: &Path) -> Result<Vec<(String, State)>> {
    pack.manifest
        .files
        .iter()
        .map(|entry| Ok((entry.path.clone(), state(entry, &safe_path(game, &entry.path)?)?)))
        .collect()
}

/// Checks every file first and writes only when all of them can be written. Originals are kept as `<file>.orig`
/// (never overwritten by a later install, so they stay the pristine files).
pub fn install(pack: &Pack, game: &Path, log: &mut dyn FnMut(&str)) -> Result<()> {
    let states = verify(pack, game)?;
    let wrong: Vec<_> = states
        .iter()
        .filter(|(_, state)| *state == State::Mismatch)
        .map(|(path, _)| path.as_str())
        .collect();
    if !wrong.is_empty() {
        bail!(
            "эти файлы не соответствуют версии игры, для которой сделан перевод, ничего не записано: {}",
            wrong.join(", ")
        );
    }
    for (index, (entry, (_, state))) in pack.manifest.files.iter().zip(&states).enumerate() {
        if *state == State::Installed {
            log(&format!("{}: уже установлен", entry.path));
            continue;
        }
        log(&format!("{}: записан", entry.path));
        let target = safe_path(game, &entry.path)?;
        let orig = sibling(&target, ".orig");
        let output = if entry.input_sha256.is_some() {
            let source = fs::read(if orig.is_file() { &orig } else { &target })?;
            let mut output = Vec::new();
            Bspatch::new(pack.blob(index))
                .and_then(|patch| patch.apply(&source, &mut output))
                .with_context(|| format!("не удаётся применить патч к {}", entry.path))?;
            output
        } else {
            pack.blob(index).to_vec()
        };
        if sha256_bytes(&output) != entry.output_sha256 {
            bail!(
                "{}: результат не совпадает с ожидаемым хэшем, оригинал не тронут",
                entry.path
            );
        }
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
        }
        let temp = sibling(&target, ".new");
        fs::write(&temp, &output)?;
        if target.is_file() && !orig.is_file() {
            fs::rename(&target, &orig)?;
        }
        fs::rename(&temp, &target)?; // replaces an existing target
    }
    Ok(())
}

/// Puts the `.orig` files back; files the pack added (no `.orig`) are removed if they are still the translated ones.
pub fn restore(pack: &Pack, game: &Path, log: &mut dyn FnMut(&str)) -> Result<()> {
    for entry in &pack.manifest.files {
        let target = safe_path(game, &entry.path)?;
        let orig = sibling(&target, ".orig");
        if orig.is_file() {
            log(&format!("{}: восстановлен", entry.path));
            fs::rename(&orig, &target)?;
        } else if target.is_file() && sha256_file(&target)? == entry.output_sha256 {
            log(&format!("{}: удалён", entry.path));
            fs::remove_file(&target)?;
        }
    }
    Ok(())
}
