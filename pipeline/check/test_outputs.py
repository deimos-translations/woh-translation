"""Тесты двух записей файлов: защиты patch.py от записи без изменений и цикла carry/apply в woh_txt.py. Только стандартная библиотека.

Использование: python -I pipeline/check/test_outputs.py   (обычно `woh.py check`)
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
    data[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", data, pe + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, pe + 20, 0xF0)  # SizeOfOptionalHeader
    struct.pack_into("<8sIIII", data, pe + 24 + 0xF0, b".text", 0x100, 0x1000, 0x200, 0x200)
    return bytes(data)


class NoChangeGuardTest(unittest.TestCase):
    def test_no_change_returns_false_and_writes_an_identical_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            src, dst = tmp / "in.exe", tmp / "out.exe"
            src.write_bytes(minimal_pe())
            self.assertFalse(patch.main(src, dst, tmp, None))
            self.assertEqual(dst.read_bytes(), src.read_bytes())


class TranslationRoundTripTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        self.source, self.translation, self.output = root / "source", root / "translation", root / "output"
        self.source.mkdir()
        (self.source / "woh_a.jn").write_bytes(b"English|Japanese\r\nHELLO|KANA\r\nBYE|KANA2")
        for target, name, value in ((woh_txt, "LANGUAGE", self.translation), (woh_txt, "OUTPUT", self.output),
                                    (common, "require_pristine", lambda path: None), (common, "record_produced", lambda *paths: None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_carry_then_apply_writes_translations_in_source_order(self):
        woh_txt.carry(self.source)
        self.assertEqual((self.translation / "woh_a.txt").read_bytes(), b"HELLO|\r\nBYE|")
        (self.translation / "woh_a.txt").write_bytes(b"HELLO|HI\r\nBYE|BYE RU")
        woh_txt.apply(self.source)
        self.assertEqual((self.output / "woh_a.jn").read_bytes(), b"English|Japanese\r\nHI|KANA\r\nBYE RU|KANA2")

    def test_apply_stops_on_a_language_file_without_a_txt(self):
        woh_txt.carry(self.source)
        (self.translation / "woh_a.txt").unlink()
        with self.assertRaises(SystemExit):
            woh_txt.apply(self.source)
        self.assertFalse((self.output / "woh_a.jn").exists())


if __name__ == "__main__":
    unittest.main()
