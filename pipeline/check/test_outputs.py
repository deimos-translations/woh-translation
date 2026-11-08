"""Tests of file writing: patch.py's guards against writing without changes, the carry/apply cycle in woh_txt.py and the hashes.txt hash checks. Standard library only.

Usage: python -I pipeline/check/test_outputs.py   (usually `woh.py check`)
"""

import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(HERE), str(HERE / "act")]  # -I does not add the script directory
import common
import patch
import woh_txt


def minimal_pe():
    """The smallest PE32+ file patch.py reads: a header, one section table entry, no code."""
    data = bytearray(0x200)
    pe = 0x40
    struct.pack_into("<I", data, 0x3C, pe)
    data[pe : pe + 4] = b"PE\0\0"
    struct.pack_into("<H", data, pe + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, pe + 20, 0xF0)  # SizeOfOptionalHeader
    struct.pack_into(
        "<8sIIII", data, pe + 24 + 0xF0, b".text", 0x100, 0x1000, 0x200, 0x200
    )
    return bytes(data)


class NoChangeGuardTest(unittest.TestCase):
    def test_no_change_returns_false_and_writes_an_identical_copy(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = pathlib.Path(tmp_name)
            src, dst = tmp / "in.exe", tmp / "out.exe"
            src.write_bytes(minimal_pe())
            self.assertFalse(patch.main(src, dst, tmp, None))
            self.assertEqual(dst.read_bytes(), src.read_bytes())


class TranslationRoundTripTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        self.source, self.translation, self.output = (
            root / "source",
            root / "translation",
            root / "output",
        )
        self.source.mkdir()
        (self.source / "woh_a.jn").write_bytes(
            b"English|Japanese\r\nHELLO|KANA\r\nBYE|KANA2"
        )
        for target, name, value in (
            (woh_txt, "LANGUAGE", self.translation),
            (woh_txt, "OUTPUT", self.output),
            (common, "require_pristine", lambda _path: None),
            (common, "record_produced", lambda *_paths: None),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_carry_then_apply_writes_translations_in_source_order(self):
        woh_txt.carry(self.source)
        self.assertEqual(
            (self.translation / "woh_a.txt").read_bytes(), b"HELLO|\r\nBYE|"
        )
        (self.translation / "woh_a.txt").write_bytes(b"HELLO|HI\nBYE|BYE RU")
        woh_txt.apply(self.source)
        self.assertEqual(
            (self.output / "woh_a.jn").read_bytes(),
            b"English|Japanese\r\nHI|KANA\r\nBYE RU|KANA2",
        )

    def test_apply_reads_txt_with_lf_or_crlf(self):
        woh_txt.carry(self.source)
        for eol in (b"\n", b"\r\n"):
            with self.subTest(eol=eol):
                (self.translation / "woh_a.txt").write_bytes(
                    b"HELLO|HI" + eol + b"BYE|BYE RU" + eol
                )
                woh_txt.apply(self.source)
                self.assertEqual(
                    (self.output / "woh_a.jn").read_bytes(),
                    b"English|Japanese\r\nHI|KANA\r\nBYE RU|KANA2",
                )

    def test_carry_keeps_translations_of_an_lf_txt(self):
        self.translation.mkdir()
        (self.translation / "woh_a.txt").write_bytes(b"HELLO|HI\nBYE|BYE RU")
        woh_txt.carry(self.source)
        self.assertEqual(
            (self.translation / "woh_a.txt").read_bytes(), b"HELLO|HI\r\nBYE|BYE RU"
        )

    def test_untranslated_output_equal_to_source_is_not_recorded(self):
        woh_txt.carry(self.source)
        with mock.patch.object(common, "record_produced") as record:
            woh_txt.apply(self.source)
        record.assert_not_called()

    def test_apply_stops_on_a_language_file_without_a_txt(self):
        woh_txt.carry(self.source)
        (self.translation / "woh_a.txt").unlink()
        with self.assertRaises(SystemExit):
            woh_txt.apply(self.source)
        self.assertFalse((self.output / "woh_a.jn").exists())


class HashesTest(unittest.TestCase):
    def test_only_a_recorded_name_with_another_hash_is_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            hashes = pathlib.Path(tmp, "hashes.txt")
            hashes.write_text("aaa\tone.png\nbbb\ttwo.png\n", encoding="utf-8")
            with mock.patch.object(common, "HASHES", hashes):
                self.assertEqual(
                    common.changed_hashes(
                        {"one.png": "aaa", "two.png": "ccc", "three.png": "ddd"}
                    ),
                    ["two.png"],
                )
                common.record_hashes(
                    lambda name: name.endswith(".png"),
                    [("ccc", "two.png"), ("ddd", "three.png")],
                )  # accepted: replaces, adds, drops one.png
                self.assertEqual(
                    common.read_hashes(), {"two.png": "ccc", "three.png": "ddd"}
                )
                self.assertEqual(
                    common.changed_hashes({"two.png": "ccc", "three.png": "ddd"}), []
                )


if __name__ == "__main__":
    unittest.main()
