# /// script
# dependencies = ["rapidocr-onnxruntime", "numpy", "pillow"]
# ///
"""OCR every extracted sprite frame and record the text found in it.

Tab-separated output, one found text per line: <frame file name> <TAB> <text>

Usage:
  uv run pipeline/act/ocr_sprites.py [--sprites DIR] [--out FILE]   (usually `woh.py ocr`)
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parent.parent.parent
SCALE = 4  # pixel-art text is unreadable at 1x
MIN_CONF = 0.5
CJK = re.compile(r"[぀-ヿ一-鿿]")
LATIN_WORD = re.compile(r"[^\W\d_]")


def is_text(text):
    return len(LATIN_WORD.findall(text)) >= 3 or len(CJK.findall(text)) >= 2


def prep(path):
    # Sprites are RGBA; composite on white so transparent pixels read as background.
    img = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    canvas.alpha_composite(img)
    scaled = canvas.convert("RGB").resize(
        (img.width * SCALE, img.height * SCALE), Image.NEAREST
    )
    return np.asarray(scaled)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sprites",
        type=Path,
        default=ROOT / "img" / "source",
        help="folder of extracted PNG frames",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "output" / "ocr_text.txt",
        help="output text file",
    )
    args = parser.parse_args()

    frames = sorted(args.sprites.glob("*.png"))
    if not frames:
        sys.exit(f"No PNG frames in {args.sprites}; run `woh.py extract` first.")

    engine = RapidOCR()
    with args.out.open("w", encoding="utf-8", newline="\n") as out:
        for i, frame in enumerate(frames, 1):
            result, _ = engine(prep(frame))
            for _, raw_text, conf in result or []:
                text = " ".join(raw_text.split())
                if (
                    conf >= MIN_CONF
                    and sum(ch.isalnum() for ch in text) >= 2
                    and is_text(text)
                ):
                    out.write(f"{frame.name}\t{text}\n")
            if i % 500 == 0:
                print(f"{i}/{len(frames)}", file=sys.stderr, flush=True)

    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
