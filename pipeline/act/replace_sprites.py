"""Заменяет кадры спрайтов и атласы шрифтов в data.win на PNG из двух папок, сопоставляя по имени.

Каждый PNG кадра должен называться <sprite>_<frame>.png (как его записывает `woh.py extract`). Файлы, чьи спрайт или кадр отсутствуют в
data.win, пропускаются с сообщением. Каждый PNG кадра должен быть дополненной ограничивающей рамкой заменяемого кадра (как при экспорте), а каждый PNG шрифта (с именем <font>.png) — размером заменяемого атласа; иначе запуск завершится ошибкой.

Запускает replace_sprites.csx через UndertaleModCli и сохраняет результат в --out.

Использование:
  python -I pipeline/act/replace_sprites.py [--images DIR] [--fonts DIR] [--data DATA.WIN] [--out OUT.WIN] [--utmt UndertaleModCli.exe]

--data по умолчанию указывает на установку Steam. --utmt берёт путь из переменной окружения UTMT_CLI, затем ищет UndertaleModCli в PATH.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=Path, default=common.ROOT / "img" / "translation", help="папка файлов <sprite>_<frame>.png")
    parser.add_argument("--fonts", type=Path, default=common.ROOT / "img" / "translation" / "font", help="папка атласов <font>.png")
    parser.add_argument("--data", type=Path, default=common.STEAM / common.DATA_WIN, help="data.win для чтения")
    parser.add_argument("--out", type=Path, default=common.OUTPUT / common.DATA_WIN, help="изменённый data.win для записи")
    parser.add_argument("--utmt", default=os.environ.get("UTMT_CLI") or shutil.which("UndertaleModCli"), help="исполняемый файл UndertaleModCli")
    args = parser.parse_args()

    if not args.utmt:
        sys.exit("UndertaleModCli not found: pass --utmt or set UTMT_CLI.")
    if not args.images.is_dir():
        sys.exit(f"Image folder not found: {args.images}")
    if not args.fonts.is_dir():
        sys.exit(f"Font folder not found: {args.fonts}")

    common.require_pristine(args.data)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "WOH_IN": str(args.images.resolve()), "WOH_FONTS": str(args.fonts.resolve())}
    subprocess.run(
        [
            args.utmt, "load", str(args.data.resolve()),
            "-s", str(HERE / "replace_sprites.csx"),
            "-o", str(args.out.resolve()), "-f",
        ],
        env=env,
        check=True,
    )
    common.record_produced(args.out)


if __name__ == "__main__":
    main()
