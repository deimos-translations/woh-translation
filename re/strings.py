"""Create or refresh the translation document re/strings/strings.txt.

Usage: python -I re/strings.py

One line per distinct string: `source<#>translation`. Control characters are escaped as `\\`, `\r`, `\n`, `\t`
and `#` is the game's own line break, so keep both as they are. An empty translation leaves the string untouched.
The first four lines (`DOOM`, `STA`, `REA`, `ALL`) are the battle damage labels: what the combat screens show for that
damage type. They are not copies of strings in the exe, so an empty one keeps its English text.
Existing translations are kept, so the command can be re-run after the target list changes.
Apply the document with `python -I re/patch.py <input exe> <output exe> re/strings/strings.txt`. Translations are applied when the game
draws the text, so the values the game logic compares are never changed; add `--literal` to also replace the exe's own copies of
texts that no code compares (reaches text that is modified before drawing).
"""
SEPARATOR = "<#>"
LABEL_KEYS = ["DOOM", "STA", "REA", "ALL"]  # battle damage labels, same list in re/patch.py
TARGETS = "re/strings/targets.tsv"
DOCUMENT = "re/strings/strings.txt"


def main():
    sources = list(LABEL_KEYS)
    for line in open(TARGETS, encoding="utf-8", newline=""):
        text = line.rstrip("\n").split("\t")[1]
        if text not in sources:
            sources.append(text)
    existing = {}
    try:
        for line in open(DOCUMENT, encoding="utf-8", newline=""):
            source, _, translation = line.rstrip("\n").partition(SEPARATOR)
            existing[source] = translation
    except FileNotFoundError:
        pass
    with open(DOCUMENT, "w", encoding="utf-8", newline="") as out:
        for text in sources:
            out.write(f"{text}{SEPARATOR}{existing.get(text, '')}\n")
    print(f"{len(sources)} strings, {sum(1 for t in sources if existing.get(t))} already translated -> {DOCUMENT}")


if __name__ == "__main__":
    main()
