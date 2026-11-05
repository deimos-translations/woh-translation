"""Create or refresh the translation document translation/exe_strings.txt.

Usage: python -I pipeline/act/exe_strings.py <targets.tsv> [document]   (normally `woh.py sync`)

One line per distinct string: `source<#>translation`. Control characters are escaped as `\\`, `\r`, `\n`, `\t`
and `#` is the game's own line break, so keep both as they are. An empty translation leaves the string untouched.
The first four lines (`DOOM`, `STA`, `REA`, `ALL`) are the battle damage labels: what the combat screens show for that
damage type. They are not copies of strings in the exe, so an empty one keeps its English text.
Existing translations are kept, so the command can be re-run after the target list changes; translations of strings that left the
game are reported as dropped. Translations are applied when the game draws the text (`woh.py exe`), so the values the game logic
compares are never changed; add `--literal` to also replace the exe's own copies of texts that no code compares.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common  # noqa: E402
from common import LABEL_KEYS, SEPARATOR  # noqa: E402


def main(targets, document):
    sources = dict.fromkeys(LABEL_KEYS)
    for line in open(targets, encoding="utf-8", newline=""):
        sources[line.rstrip("\n").split("\t")[1]] = None
    existing = {}
    if document.exists():
        for line in open(document, encoding="utf-8", newline=""):
            source, _, translation = line.rstrip("\n").partition(SEPARATOR)
            existing[source] = translation
    with open(document, "w", encoding="utf-8", newline="") as out:
        for text in sources:
            out.write(f"{text}{SEPARATOR}{existing.get(text, '')}\n")
    dropped = [text for text, translation in existing.items() if translation and text not in sources]
    print(f"{len(sources)} strings, {sum(1 for text in sources if existing.get(text))} already translated, {len(dropped)} translations dropped -> {document}")
    for text in dropped:
        print(f"  dropped: {text!a} = {existing[text]!a}")


if __name__ == "__main__":
    main(sys.argv[1], pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else common.TRANSLATION / "exe_strings.txt")
