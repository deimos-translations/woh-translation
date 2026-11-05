"""Build targets.tsv (every code-referenced copy of every translatable string) for the analysed build.

Usage: python -I pipeline/generate/make_targets.py <pool_strings.tsv> <exe_strings.txt> <patch_sites.tsv> <targets.tsv>

pool_strings.tsv comes from ExportPoolStrings.java: every address of the game's string pool that code references, with the text found
there. Only referenced addresses are copies that matter, and a referenced address is a copy even when no NUL precedes it (it follows
binary data) or when it points into a longer literal. A byte scan finds neither case reliably.

Translatable texts are: the sources in the translation document, plus every short ALL-CAPS token (`PREP`, `S.ATK`, `MAGIC`, ...) and
quoted ALL-CAPS name (`'HAPPY LEMON'`), except the damage-type keys and label strings that patch.py handles itself. Output lines:
`<hex VA>\t<escaped text>`, with `\\`, CR, LF and TAB written as `\\\\`, `\\r`, `\\n`, `\\t`. Texts with no code reference are reported.
"""
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
from common import LABEL_KEYS, SEPARATOR  # noqa: E402

UNESCAPES = {"\\\\": "\\", "\\r": "\r", "\\n": "\n", "\\t": "\t"}


def escape(text):
    return "".join({"\\": "\\\\", "\r": "\\r", "\n": "\\n", "\t": "\\t"}.get(char, char) for char in text)


def unescape(text):
    return re.sub(r"\\[\\rnt]", lambda match: UNESCAPES[match.group()], text)


def is_label_like(text):
    """Short ALL-CAPS tokens (action codes, item categories, tags) and quoted ALL-CAPS names."""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.'\-]+", text) or re.fullmatch(r"'[A-Z][A-Z .]+'", text))


def label_literals(patch_sites_path):
    """The literals patch.py repoints itself (the label slots' Polish text); translating them here would collide."""
    return {line.split("\t")[6].rstrip("\n") for line in open(patch_sites_path, encoding="utf-8") if line.startswith("slot\t")}


def main(pool_path, document_path, patch_sites_path, targets_path):
    pool = []  # (VA, text) in address order
    for line in open(pool_path, encoding="utf-8", newline=""):
        va, text, _count = line.rstrip("\n").split("\t")
        pool.append((va, unescape(text)))

    excluded = set(LABEL_KEYS) | label_literals(patch_sites_path)
    wanted = {}  # insertion-ordered set: the document's order is the order of earlier target lists
    document = pathlib.Path(document_path)
    if document.exists():
        for line in open(document, encoding="utf-8", newline=""):
            text = unescape(line.rstrip("\r\n").partition(SEPARATOR)[0])
            if text not in excluded:
                wanted[text] = None

    added = []
    for _va, text in pool:
        if text not in wanted and text not in excluded and is_label_like(text):
            wanted[text] = None
            added.append(text)

    copies = collections.defaultdict(list)
    for va, text in pool:
        if text in wanted:
            copies[text].append(va)

    lines = [f"{va}\t{escape(text)}\n" for text in wanted for va in copies[text]]
    with open(targets_path, "w", encoding="utf-8", newline="") as out:
        out.writelines(lines)

    missing = [text for text in wanted if not copies[text]]
    print(f"{len(wanted) - len(missing)} texts with code-referenced copies, {len(lines)} copies, {len(added)} added by the ALL-CAPS rule")
    for text in missing:
        print(f"  no code reference (dropped): {text!a}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
