"""Reconciles the translation document translation/exe_strings.txt with this build's target list and writes a report of new exe texts.

Usage: python -I pipeline/act/exe_strings.py <targets.tsv> <candidates.txt> [document]   (usually `woh.py sync`)

The document is maintained by hand and contains only translatable strings: sync does not change it. Texts from the target list that are missing from the document are written to
candidates.txt in the same format (`source|`), so that wanted lines can be moved into the document by hand (after a game update, or for found texts).

Line format, escapes and the `!` mark: README.md, "Как заполнять `exe_strings.txt`". The first four lines (`DOOM`, `STA`, `REA`, `ALL`) are
combat damage labels, not copies of strings in the exe, so an empty translation keeps the English text.
Reports document lines with no copy in this build's code and lines without a translation.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common
from common import LABEL_KEYS, LITERAL_MARK, SEPARATOR


def main(targets, candidates, document):
    entries = {}  # escaped source -> translation
    with pathlib.Path(document).open(encoding="utf-8", newline="") as file:
        for line in file.read().split("\n"):
            if line:
                _literal, source, _, translation = common.parse_entry(line)
                entries[common.escape(common.unescape(source))] = (
                    translation  # `\!` and `!` name the same source
                )
    found, new = set(), []
    with pathlib.Path(targets).open(encoding="utf-8", newline="") as file:
        for line in file.read().split("\n"):
            if line:
                text = line.split("\t")[1]
                if text in found:
                    continue
                found.add(text)
                if text not in entries:
                    new.append(text)
    with pathlib.Path(candidates).open("w", encoding="utf-8", newline="") as out:
        for text in new:
            out.write(
                f"{'\\' if text.startswith(LITERAL_MARK) else ''}{text}{SEPARATOR}\n"
            )
    print(
        f"{len(entries)} entries in {document.name}, {len(new)} exe texts not in it -> {pathlib.Path(candidates).resolve()}"
    )
    for text, translation in entries.items():
        if text not in found and text not in LABEL_KEYS:
            print(f"  no code copy in this build: {text}")
        if not translation:
            print(f"  no translation: {text}")


if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2],
        pathlib.Path(sys.argv[3])
        if len(sys.argv) > 3
        else common.TRANSLATION / "exe_strings.txt",
    )
