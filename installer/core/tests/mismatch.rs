//! Installing against files whose hashes differ from the recorded ones. Small synthetic files; no game needed.

use qbsdiff::Bsdiff;
use std::{fs, path::Path};
use tempfile::TempDir;
use woh_patcher_core::{Entry, Manifest, Pack, State, install, restore, sha256_bytes, verify};

const EXE: &str = "game.exe";
const TEXT: &str = "language/text.jn";

fn original() -> Vec<u8> {
    (0..20_000u32).map(|index| (index * 7 % 251) as u8).collect()
}

fn translated() -> Vec<u8> {
    let mut data = original();
    data[1000..1100].fill(0xAA);
    data.extend_from_slice(b"appended");
    data
}

/// A pack with a patched exe and a whole-file text. `output_hash` replaces the exe's expected output hash when given.
fn pack(exe_output_hash: Option<String>) -> Pack {
    let (source, target) = (original(), translated());
    let mut patch = Vec::new();
    Bsdiff::new(&source, &target).compare(&mut patch).unwrap();
    let text = b"translated text".to_vec();
    let manifest = Manifest {
        version: "test".into(),
        files: vec![
            Entry {
                path: EXE.into(),
                input_sha256: Some(sha256_bytes(&source)),
                output_sha256: exe_output_hash.unwrap_or_else(|| sha256_bytes(&target)),
                blob_len: patch.len() as u64,
            },
            Entry {
                path: TEXT.into(),
                input_sha256: None,
                output_sha256: sha256_bytes(&text),
                blob_len: text.len() as u64,
            },
        ],
    };
    Pack::decode(&Pack::encode(&manifest, &[&patch, &text]).unwrap()).unwrap()
}

fn game(exe: &[u8]) -> TempDir {
    let dir = TempDir::new().unwrap();
    fs::write(dir.path().join(EXE), exe).unwrap();
    fs::create_dir(dir.path().join("language")).unwrap();
    fs::write(dir.path().join(TEXT), b"english text").unwrap();
    dir
}

fn no_leftovers(root: &Path) {
    for name in [EXE, TEXT] {
        for suffix in [".orig", ".new"] {
            assert!(!root.join(format!("{name}{suffix}")).exists(), "{name}{suffix} exists");
        }
    }
}

#[test]
fn hash_mismatches_are_refused_and_nothing_is_written() {
    let log = &mut |_: &str| {};

    // 1. The exe is another version: refused as a whole, so the text file (which would match) is not written either.
    let mut other = original();
    other[5] ^= 1;
    let foreign = game(&other);
    let error = install(&pack(None), foreign.path(), log).unwrap_err().to_string();
    assert!(error.contains(EXE), "{error}");
    assert_eq!(fs::read(foreign.path().join(EXE)).unwrap(), other);
    assert_eq!(fs::read(foreign.path().join(TEXT)).unwrap(), b"english text");
    no_leftovers(foreign.path());
    assert_eq!(verify(&pack(None), foreign.path()).unwrap()[0].1, State::Mismatch);

    // 2. The patch result does not match the recorded output hash: the original is left alone.
    let pristine = game(&original());
    let bad = pack(Some(sha256_bytes(b"something else")));
    assert!(
        install(&bad, pristine.path(), log)
            .unwrap_err()
            .to_string()
            .contains("хэш")
    );
    assert_eq!(fs::read(pristine.path().join(EXE)).unwrap(), original());
    no_leftovers(pristine.path());

    // 3. A good install, then the backup is tampered with: the next install refuses to patch from it.
    let good = pack(None);
    install(&good, pristine.path(), log).unwrap();
    assert_eq!(fs::read(pristine.path().join(EXE)).unwrap(), translated());
    assert!(
        verify(&good, pristine.path())
            .unwrap()
            .iter()
            .all(|(_, state)| *state == State::Installed)
    );
    fs::write(pristine.path().join(EXE), b"replaced by another update").unwrap();
    fs::write(pristine.path().join(format!("{EXE}.orig")), b"tampered backup").unwrap();
    assert_eq!(verify(&good, pristine.path()).unwrap()[0].1, State::Mismatch);
    assert!(install(&good, pristine.path(), log).is_err());
    assert_eq!(
        fs::read(pristine.path().join(EXE)).unwrap(),
        b"replaced by another update"
    );

    // 4. restore does not delete a file it added once the user changed it.
    let added = game(&original());
    let manifest = Manifest {
        version: "t".into(),
        files: vec![Entry {
            path: "extra.txt".into(),
            input_sha256: None,
            output_sha256: sha256_bytes(b"ours"),
            blob_len: 4,
        }],
    };
    let extra = Pack::decode(&Pack::encode(&manifest, &[b"ours"]).unwrap()).unwrap();
    install(&extra, added.path(), log).unwrap();
    fs::write(added.path().join("extra.txt"), b"edited by the user").unwrap();
    restore(&extra, added.path(), log).unwrap();
    assert_eq!(fs::read(added.path().join("extra.txt")).unwrap(), b"edited by the user");
}
