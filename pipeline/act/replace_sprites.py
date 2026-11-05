"""Replace sprite frames and font atlases in a data.win with PNGs from two folders, matched by name.

Each frame PNG must be named <sprite>_<frame>.png (as written by `woh.py extract`). Files whose sprite or frame does not exist in the
data.win are skipped with a message. Each frame PNG and each font PNG (named <font>.png) must have the size of the texture it replaces, otherwise the run fails.

Runs replace_sprites.csx through UndertaleModCli and saves the result to --out.

Usage:
  python -I pipeline/act/replace_sprites.py [--images DIR] [--fonts DIR] [--data DATA.WIN] [--out OUT.WIN] [--utmt UndertaleModCli.exe]

--data defaults to the Steam install. --utmt falls back to the UTMT_CLI env var, then UndertaleModCli on PATH.
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
    parser.add_argument("--images", type=Path, default=common.ROOT / "img" / "translation", help="folder of <sprite>_<frame>.png files")
    parser.add_argument("--fonts", type=Path, default=common.ROOT / "font", help="folder of <font>.png atlases")
    parser.add_argument("--data", type=Path, default=common.STEAM / common.DATA_WIN, help="data.win to read")
    parser.add_argument("--out", type=Path, default=common.OUTPUT / common.DATA_WIN, help="modified data.win to write")
    parser.add_argument("--utmt", default=os.environ.get("UTMT_CLI") or shutil.which("UndertaleModCli"), help="UndertaleModCli executable")
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
