"""Rebuild re/strings/targets.tsv (every code-referenced copy of every translatable string) for a given build of the exe.

Usage: python -I re/scripts/make_targets.py <exe> <pool_strings.tsv> <old targets.tsv> <new targets.tsv>

pool_strings.tsv comes from re/scripts/ExportPoolStrings.java: every address of the game's string pool that code references,
with the text found there. Only referenced addresses are copies that matter, and a referenced address is a copy even when no NUL
precedes it (it follows binary data) or when it points into a longer literal. A byte scan finds neither case reliably.

Translatable texts are: the texts of the old targets.tsv, plus every short ALL-CAPS token (`PREP`, `S.ATK`, `MAGIC`, ...) and quoted
ALL-CAPS name (`'HAPPY LEMON'`), except the damage-type keys and label strings that re/patch.py handles itself. Output lines: `<hex VA>\t<escaped text>`, with `\\`, CR, LF
and TAB written as `\\\\`, `\\r`, `\\n`, `\\t`. Texts that vanished and changed copy counts are reported.
"""
import collections
import re
import sys

LABEL_KEYS = ["DOOM", "STA", "REA", "ALL"]  # logic keys of the battle damage types, same list in re/patch.py
UNESCAPES = {"\\\\": "\\", "\\r": "\r", "\\n": "\n", "\\t": "\t"}


def escape(text):
    return "".join({"\\": "\\\\", "\r": "\\r", "\n": "\\n", "\t": "\\t"}.get(char, char) for char in text)


def unescape(text):
    return re.sub(r"\\[\\rnt]", lambda match: UNESCAPES[match.group()], text)


def is_label_like(text):
    """Short ALL-CAPS tokens (action codes, item categories, tags) and quoted ALL-CAPS names."""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.'\-]+", text) or re.fullmatch(r"'[A-Z][A-Z .]+'", text))


def label_literals():
    """The literals re/patch.py repoints itself (the label slots' Polish text); translating them here would collide."""
    return {line.split("\t")[6].rstrip("\n") for line in open("re/patch_sites.tsv", encoding="utf-8")
            if line.startswith("slot\t")}


def main(exe_path, pool_path, old_targets_path, new_targets_path):
    pool = []  # (VA, text) in address order
    for line in open(pool_path, encoding="utf-8", newline=""):
        va, text, _count = line.rstrip("\n").split("\t")
        pool.append((va, unescape(text)))

    wanted, old_copies = [], collections.Counter()
    for line in open(old_targets_path, encoding="utf-8", newline=""):
        text = unescape(line.rstrip("\n").split("\t")[1])
        if text not in old_copies:
            wanted.append(text)
        old_copies[text] += 1
    wanted_set = set(wanted)
    excluded = set(LABEL_KEYS) | label_literals()

    added = []
    for _va, text in pool:
        if text not in wanted_set and text not in excluded and is_label_like(text):
            wanted.append(text)
            wanted_set.add(text)
            added.append(text)

    copies = collections.defaultdict(list)
    for va, text in pool:
        if text in wanted_set and text not in excluded:
            copies[text].append(va)

    lines = [f"{va}\t{escape(text)}\n" for text in wanted for va in copies[text]]
    with open(new_targets_path, "w", encoding="utf-8", newline="") as out:
        out.write("".join(lines))

    missing = [text for text in wanted if not copies[text]]
    changed = [text for text in wanted
               if text not in added and copies[text] and len(copies[text]) != old_copies[text]]
    print(f"{len(wanted) - len(missing)} texts with code-referenced copies, {len(lines)} copies (was {sum(old_copies.values())}),"
          f" {len(added)} added by the ALL-CAPS rule")
    for text in missing:
        print(f"  no code reference (dropped): {text!a}")
    for text in changed:
        print(f"  copies {old_copies[text]} -> {len(copies[text])}: {text!a}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
