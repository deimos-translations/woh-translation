# /// script
# dependencies = ["pillow"]
# ///
"""Check that every PNG in img/translation has a same-named PNG in img/source with the same dimensions.

Run: uv run pipeline/check/test_translation_dimensions.py   (`woh.py extract` first)
"""

import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
TRANSLATION = ROOT / "img" / "translation"
SOURCE = ROOT / "img" / "source"


class TranslationDimensionsTest(unittest.TestCase):
    def test_translation_folder_has_images(self):
        self.assertTrue(list(TRANSLATION.glob("*.png")), f"no PNGs in {TRANSLATION}")

    def test_each_translation_image_matches_source_size(self):
        for translated in sorted(TRANSLATION.glob("*.png")):
            with self.subTest(image=translated.name):
                source = SOURCE / translated.name
                self.assertTrue(source.is_file(), "no matching file in img/source")
                with Image.open(translated) as t, Image.open(source) as s:
                    self.assertEqual(t.size, s.size)


if __name__ == "__main__":
    unittest.main()
