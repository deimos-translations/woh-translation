"""Record the sha256 of the translated sprites of a World of Horror data.win in hashes.txt.

Runs pipeline/generate/export_woh.csx through UndertaleModCli into a temporary
directory, then hashes the sprite frames that have a PNG in img/translation
(the sprites the translation replaces). Fails if one of them is not in the
data.win. The exe's hash is written by `woh.py ghidra-import`.

Usage:
  python -I pipeline/act/hash_images.py [DATA.WIN] [--utmt UndertaleModCli.exe]

DATA.WIN defaults to the Steam install. --utmt falls back to the UTMT_CLI env
var, then UndertaleModCli on PATH. UndertaleModCli output goes to stderr.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common  # noqa: E402

EXPORT_SCRIPT = HERE.parent / "generate" / "export_woh.csx"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", nargs="?", type=Path, default=common.STEAM / common.DATA_WIN, help="data.win to read")
    parser.add_argument("--utmt", default=os.environ.get("UTMT_CLI") or shutil.which("UndertaleModCli"), help="UndertaleModCli executable")
    args = parser.parse_args()

    if not args.utmt:
        sys.exit("UndertaleModCli not found: pass --utmt or set UTMT_CLI.")
    if not args.data.is_file():
        sys.exit(f"data.win not found: {args.data}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        sprites = out / "sprites"
        sprites.mkdir()
        (out / "fonts").mkdir()

        env = {**os.environ, "WOH_OUT": str(out), "WOH_SPRITES": str(sprites)}
        subprocess.run(
            [args.utmt, "load", str(args.data.resolve()), "-s", str(EXPORT_SCRIPT)],
            env=env,
            check=True,
            stdout=sys.stderr,
        )

        wanted = sorted(png.name for png in (common.ROOT / "img" / "translation").glob("*.png"))
        found = {png.name: png for png in sprites.glob("*.png")}
        missing = [name for name in wanted if name not in found]
        if missing:
            sys.exit(f"not in data.win: {', '.join(missing)}")
        common.record_hashes(".png", [(common.sha256(found[name]), name) for name in wanted])
        print(f"hashes.txt: {len(wanted)} sprites")


if __name__ == "__main__":
    main()
