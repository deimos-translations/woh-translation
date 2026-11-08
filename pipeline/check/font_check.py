# /// script
# dependencies = ["pillow"]
# ///
"""Compares the edited font sheets in img/translation/font with the game's sheets from the current data.win.

    uv run pipeline/check/font_check.py <img/translation/font> <img/source/font> <out/extract/fonts>

The sheet size must match the game's (otherwise replace_sprites.py will not replace the font). glyphs_<font>.csv shows where
each character lies: the characters whose cells differ from the game's are listed. Pixels outside all cells belong to no character;
if they are changed, the check fails.
"""

import pathlib
import sys

from PIL import Image, ImageChops, ImageDraw


def glyph_cells(csv_path):
    """(character code, (left, top, right, bottom)) for each glyph row of a glyphs_<font>.csv; the first line is the font's header."""
    with pathlib.Path(csv_path).open(encoding="utf-8") as file:
        next(file)
        for line in file:
            if line.strip():
                code, x, y, width, height, _shift, _offset = map(
                    int, line.rstrip("\n").split(";")
                )
                if width and height:  # an empty cell (space) has no pixels to differ
                    yield code, (x, y, x + width, y + height)


def drawn(image):
    """RGBA with the colour of fully transparent pixels zeroed: the colour under alpha 0 is never drawn, so it does not count as a change."""
    rgba = image.convert("RGBA")
    return Image.composite(
        rgba, Image.new("RGBA", rgba.size, (0, 0, 0, 0)), rgba.getchannel("A")
    )


def check(edited_path, game_path, csv_path):
    """Print the characters whose cells differ from the game's; return False when pixels outside every glyph cell differ."""
    with Image.open(edited_path) as edited, Image.open(game_path) as game:
        if edited.size != game.size:
            sys.exit(f"{edited_path.name}: {edited.size} is not the game's {game.size}")
        difference = ImageChops.difference(drawn(edited), drawn(game))
    diff = Image.new("L", difference.size, 0)
    for band in difference.split():  # any channel, alpha included
        diff = ImageChops.lighter(diff, band)
    diff = diff.point(lambda value: 255 if value else 0)
    outside = diff.copy()
    draw = ImageDraw.Draw(outside)
    changed = []
    for code, (left, top, right, bottom) in glyph_cells(csv_path):
        if diff.crop((left, top, right, bottom)).getbbox():
            changed.append(chr(code))
        draw.rectangle(
            (left, top, right - 1, bottom - 1), fill=0
        )  # PIL's rectangle includes its far corner
    print(
        f"{edited_path.name}: {len(changed)} glyphs differ from the game: {''.join(changed)}"
    )
    outside_count = outside.histogram()[255]
    if outside_count:
        print(
            f"  {outside_count} changed pixels outside every glyph cell, bounds {outside.getbbox()}"
        )
    return not outside_count


def main(translation_dir, source_dir, glyph_dir):
    translation, source, glyphs = (
        pathlib.Path(translation_dir),
        pathlib.Path(source_dir),
        pathlib.Path(glyph_dir),
    )
    results = []
    for edited in sorted(translation.glob("*.png")):
        game = source / edited.name
        if not game.is_file():
            sys.exit(f"no game atlas {game}")
        results.append(check(edited, game, glyphs / f"glyphs_{edited.stem}.csv"))
    if not all(results):
        sys.exit("pixels outside the glyph cells changed")


if __name__ == "__main__":
    main(*sys.argv[1:4])
