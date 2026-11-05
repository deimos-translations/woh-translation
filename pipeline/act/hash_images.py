"""Hash every image extracted from a World of Horror data.win.

Runs pipeline/generate/export_woh.csx through UndertaleModCli into a temporary
directory, then prints one line per PNG (sprite frames and font atlases):
  <sha256><TAB><relative path>

Usage:
  python -I pipeline/act/hash_images.py [DATA.WIN] [--utmt UndertaleModCli.exe] > hashes.tsv

DATA.WIN defaults to the Steam install. --utmt falls back to the UTMT_CLI env
var, then UndertaleModCli on PATH. UndertaleModCli output goes to stderr.
"""

import argparse
import hashlib
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

        for png in sorted(out.rglob("*.png"), key=lambda p: p.relative_to(out).as_posix()):
            with png.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            print(f"{digest}\t{png.relative_to(out).as_posix()}")


if __name__ == "__main__":
    main()
