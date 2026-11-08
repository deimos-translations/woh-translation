"""Checks that the installer reproduces the pipeline's output: packs the Steam game files against output/ with woh-pack, installs the pack
into a temporary copy of the game with wohrus, and compares every file of output/ with the installed one by sha256.

Needs a finished `woh.py build` (output/), the game in the Steam folder and the release binaries (`cargo build --release` in installer/).
Takes about a minute (the bsdiff of data.win). Standard library only.

Usage: python -I pipeline/check/test_installer.py
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(HERE)]  # -I does not add the script directory
import common

RELEASE = common.ROOT / "installer" / "target" / "release"
SUFFIX = ".exe" if sys.platform == "win32" else ""


class InstallerTest(unittest.TestCase):
    def test_installed_files_equal_pipeline_output(self):
        pack_tool, installer = (
            RELEASE / ("woh-pack" + SUFFIX),
            RELEASE / ("wohrus" + SUFFIX),
        )
        for path in (pack_tool, installer, common.STEAM / common.DATA_WIN):
            if not path.is_file():
                self.skipTest(f"missing {path}")
        # The changelog is copied to output/ for the release zip; the installer does not install it.
        changelog = next(
            (path for path in common.OUTPUT.glob("*СПИСОК ИЗМЕНЕНИЙ.*")), None
        )
        built = sorted(
            path
            for path in common.OUTPUT.rglob("*")
            if path.is_file() and path != changelog
        )
        if not built:
            self.skipTest("output/ is empty: run `woh.py build`")

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = pathlib.Path(tmp_name)
            game, pack = tmp / "game", tmp / ("pack" + SUFFIX)
            shutil.copytree(
                common.STEAM,
                game,
                ignore=shutil.ignore_patterns(
                    "audiogroup*", "extra content", "wohgame.app", ".remember"
                ),
            )
            subprocess.run(
                [
                    pack_tool,
                    "--pristine",
                    common.STEAM,
                    "--built",
                    common.OUTPUT,
                    "--version",
                    "test",
                    "--exclude",
                    changelog.name if changelog else "",
                    "--installer",
                    installer,
                    "--out",
                    pack,
                ],
                check=True,
            )
            subprocess.run([pack, "install", "--game", game], check=True)

            if changelog:
                self.assertFalse(
                    (game / changelog.name).exists(), "changelog installed"
                )

            for path in built:
                relative = path.relative_to(common.OUTPUT)
                self.assertEqual(
                    common.sha256(game / relative), common.sha256(path), str(relative)
                )


if __name__ == "__main__":
    unittest.main()
