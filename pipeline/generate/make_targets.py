"""Builds targets.tsv (every copy of every translatable string referenced by code) for the analyzed build.

Usage: python -I pipeline/generate/make_targets.py <pool_strings.tsv> <exe_strings.txt> <patch_sites.tsv> <targets.tsv>

pool_strings.tsv is made by ExportPoolStrings.java: every address of the game's string pool that code references, with the text found there.
Only referenced addresses matter; a referenced address counts as a copy even if it has no NUL before it (it follows
binary data) or if it points into the middle of a longer literal. A byte-wise search finds neither case reliably.

Translatable texts: the sources from the translation document, plus every short all-caps token (`PREP`, `S.ATK`, `MAGIC`, ...) and
quoted all-caps name (`'HAPPY LEMON'`) and every text of several English words (`Logging in... DONE`, `current weather: `;
without `_`, `[`, `gml_` and backslash), except the damage-type keys and label strings that patch.py handles itself. Output lines:
`<hex VA>\t<escaped text>`, with the text written as in the document (common.escape): CRLF as `\\n`, bare LF as `\\l`, `\\r`, `\\\\` and `\\t`. Texts with no code references are reported.
"""

import collections
import pathlib
import re
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent)
)  # -I does not add the script directory
from common import LABEL_KEYS, escape, parse_entry, unescape, unescape_pool


def is_label_like(text):
    """Short ALL-CAPS tokens (action codes, item categories, tags) and quoted ALL-CAPS names."""
    return bool(
        re.fullmatch(r"[A-Z][A-Z0-9.'\-]+", text)
        or re.fullmatch(r"'[A-Z][A-Z .]+'", text)
    )


def is_english_text(text):
    """Multi-word English text (UI lines, messages). Identifiers, debug tags and code fragments are left out."""
    return (
        bool(re.search(r"[A-Za-z]{3,}", text))
        and " " in text
        and not any(mark in text for mark in ("_", "[", "gml_", "\\"))
    )


def label_literals(patch_sites_path):
    """The literals patch.py repoints itself (the label slots' Polish text); translating them here would collide."""
    return {
        line.split("\t")[6].rstrip("\n")
        for line in pathlib.Path(patch_sites_path).open(encoding="utf-8")
        if line.startswith("slot\t")
    }


def main(pool_path, document_path, patch_sites_path, targets_path):
    pool = []  # (VA, text) in address order
    with pathlib.Path(pool_path).open(encoding="utf-8", newline="") as file:
        for line in file:
            va, text, _count = line.rstrip("\n").split("\t")
            pool.append((va, unescape_pool(text)))

    excluded = set(LABEL_KEYS) | label_literals(patch_sites_path)
    wanted = {}  # insertion-ordered set: the document's order is the order of earlier target lists
    document = pathlib.Path(document_path)
    if document.exists():
        with pathlib.Path(document).open(encoding="utf-8", newline="") as file:
            for line in file:
                text = unescape(parse_entry(line.rstrip("\r\n"))[1])
                if text not in excluded:
                    wanted[text] = None

    added = []
    for _va, text in pool:
        if (
            text not in wanted
            and text not in excluded
            and (is_label_like(text) or is_english_text(text))
        ):
            wanted[text] = None
            added.append(text)

    copies = collections.defaultdict(list)
    for va, text in pool:
        if text in wanted:
            copies[text].append(va)

    lines = [f"{va}\t{escape(text)}\n" for text in wanted for va in copies[text]]
    with pathlib.Path(targets_path).open("w", encoding="utf-8", newline="") as out:
        out.writelines(lines)

    missing = [text for text in wanted if not copies[text]]
    print(
        f"{len(wanted) - len(missing)} texts with code-referenced copies, {len(lines)} copies, {len(added)} added by the caps and English-text rules"
    )
    for text in missing:
        print(f"  no code reference: {text!a}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
