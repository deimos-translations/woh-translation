use anyhow::{Context, Result, bail};
use std::{path::PathBuf, process::ExitCode};
use woh_patcher_core::{Pack, State, find_game, install, restore, verify};

const USAGE: &str = "использование: wohrus [install|restore|verify] [--game ПАПКА] [--pack ФАЙЛ]";

fn run() -> Result<()> {
    let mut args = std::env::args().skip(1).peekable();
    let command = args
        .next_if(|arg| !arg.starts_with("--"))
        .unwrap_or_else(|| "install".into());
    let (mut game, mut pack_path) = (None::<PathBuf>, std::env::current_exe()?);
    while let Some(flag) = args.next() {
        let value = args.next().with_context(|| format!("{flag} требует значение"))?;
        match flag.as_str() {
            "--game" => game = Some(value.into()),
            "--pack" => pack_path = value.into(),
            _ => bail!("{USAGE}"),
        }
    }
    let game = game
        .or_else(find_game)
        .context("папка WoH не найдена в стандартных путях Steam: укажите --game ПАПКА")?;
    let pack = Pack::read(&pack_path)?;
    println!("игра: {}\nперевод: {}", game.display(), pack.manifest.version);
    let mut log = |line: &str| println!("{line}");
    match command.as_str() {
        "install" => install(&pack, &game, &mut log),
        "restore" => restore(&pack, &game, &mut log),
        "verify" => {
            for (path, state) in verify(&pack, &game)? {
                let text = match state {
                    State::Installed => "установлен",
                    State::Ready => "готов",
                    State::Mismatch => "НЕ СОВПАДАЕТ",
                };
                println!("{path}: {text}");
            }
            Ok(())
        }
        _ => bail!("{USAGE}"),
    }
}

fn main() -> ExitCode {
    let interactive = std::env::args().len() == 1; // double-clicked: keep the console open
    let code = match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("ошибка: {error:#}");
            ExitCode::FAILURE
        }
    };
    if interactive {
        println!("Нажмите Enter для выхода.");
        let _ = std::io::stdin().read_line(&mut String::new());
    }
    code
}
