use std::path::{Path, PathBuf};

const GAME_DIR: &str = "WOH";
const GAME_EXE: &str = "worldofhorror.exe";

fn steam_roots() -> Vec<PathBuf> {
    if cfg!(windows) {
        vec![r"C:\Program Files (x86)\Steam".into(), r"C:\Program Files\Steam".into()]
    } else {
        std::env::var_os("HOME")
            .map(|home| vec![Path::new(&home).join(".local/share/Steam")])
            .unwrap_or_default()
    }
}

/// The WoH folder in a Steam library: the default Steam folders plus the `"path"` entries of their libraryfolders.vdf.
pub fn find_game() -> Option<PathBuf> {
    let mut libraries = steam_roots();
    for root in steam_roots() {
        if let Ok(text) = std::fs::read_to_string(root.join("steamapps/libraryfolders.vdf")) {
            for line in text.lines() {
                let mut quoted = line.split('"').skip(1).step_by(2);
                if quoted.next() == Some("path")
                    && let Some(value) = quoted.next()
                {
                    libraries.push(PathBuf::from(value.replace(r"\\", r"\")));
                }
            }
        }
    }
    libraries
        .into_iter()
        .map(|library| library.join("steamapps/common").join(GAME_DIR))
        .find(|game| game.join(GAME_EXE).is_file())
}
