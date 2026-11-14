"""Keeps translation/*.txt as the translation source and builds .jn files from it.

.jn format: one line "English|Japanese" per text line (woh_ui.jn also starts with a header line "English|Japanese").
woh_ver.jn is plain text without a Japanese column: its English text is the part before the first "|" (the first line repeats the English after "|", which is not saved).
txt format: one line "<eng>|<rus>" per text line of the .jn (header skipped), in the same order. An empty <rus> is written as an empty string.
The separator is the first "|" in the line.
Line endings: both formats are read with LF or CRLF and written CRLF, as the game's files and Windows checkouts of the txt files.

carry: overwrite every txt from the untranslated .jn files in --source. Each new English line gets the Russian text
  of the txt line with the same English. English lines no longer in the game are reported as removed.
apply: write every translated .jn to output/language/engLanguage. The Japanese column and header come from the --source .jn files.
  Lines are matched by English text. Fails if the txt's English text is missing from the source (run carry first);
  warns if the txt lines are in a different order than in the .jn file. A source line without a txt entry takes its
  translation from EXTRA_TRANSLATIONS (in this file), or keeps English; each such line, and each txt entry missing from the source, is a warning.

The source files must be the game's originals: files written by this pipeline are rejected.

Usage (usually `woh.py sync` and `woh.py build --no-exe --no-sprites`):
  python -I pipeline/act/woh_txt.py carry [--source DIR]
  python -I pipeline/act/woh_txt.py apply [--source DIR]

"""

import argparse
import pathlib
import re
import sys
from collections import defaultdict, deque

HEADER = "English|Japanese"
PLAIN_TEXT = {"woh_ver.jn"}
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common

SEP = common.SEPARATOR
LANGUAGE = common.TRANSLATION
OUTPUT = common.OUTPUT / common.LANGUAGE
SOURCE = common.STEAM / common.LANGUAGE
EOL = "\r\n"
EXTRA_TRANSLATIONS = {
    "woh_shichi.jn": {
        "Investigate the SEASIDE location three times to complete this quest.": "Исследуйте локацию ПОБЕРЕЖЬЕ трижды для завершения этого задания."
    },
    "woh_small.jn": {"1 KNOWLEDGE": "1 ИНТЕЛЛЕКТА"},
    # source lines the txt files lack, e.g. in another game version: {jn file: {english: russian}}
}


def read_lines(path):
    lines = re.split(r"\r?\n", path.read_bytes().decode("utf-8"))
    if lines[-1] == "":
        lines.pop()
    return lines


def split_header(lines):
    head = lines[:1] if lines and lines[0] == HEADER else []
    return head, lines[len(head) :]


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(EOL.join(lines).encode("utf-8"))


def columns(name, line):
    """Return (english, japanese); japanese is None for plain-text lines."""
    if name in PLAIN_TEXT:
        return line.partition("|")[0], None
    en, sep, ja = line.partition("|")
    return (en, ja) if sep else (line, None)


def split_entry(entry):
    """Split "<eng>|<rus>" at the first "|"."""
    en, sep, ru = entry.partition(SEP)
    return (en, ru) if sep else None


def carry(source):
    for jn_path in sorted(source.glob("*.jn")):
        common.require_pristine(jn_path)
        jn = jn_path.name
        txt = LANGUAGE / jn_path.with_suffix(".txt").name
        _, new_lines = split_header(read_lines(jn_path))

        pool = defaultdict(deque)
        for entry in read_lines(txt) if txt.exists() else []:
            parts = split_entry(entry)
            if parts is None:
                sys.exit(f"{txt.name}: line without {SEP}: {entry!r}")
            pool[parts[0]].append(parts[1])

        out = []
        unmatched = 0
        for line in new_lines:
            en = columns(jn, line)[0]
            queue = pool.get(en)
            if queue:
                ru = queue.popleft()
            else:
                ru = ""
                unmatched += 1
            out.append(f"{en}{SEP}{ru}")

        dropped = sum(1 for queue in pool.values() for ru in queue if ru)
        write_lines(txt, out)
        print(
            f"{txt.name}: {len(out)} lines, {unmatched} without a match, {dropped} translations dropped"
        )


def apply(source):
    for src in sorted(source.glob("*.jn")):
        common.require_pristine(src)
        txt = LANGUAGE / src.with_suffix(".txt").name
        if not txt.exists():
            sys.exit(f"{txt.name} is missing: run carry")
        head, source_lines = split_header(read_lines(src))
        entries = read_lines(txt)
        extra_lines = EXTRA_TRANSLATIONS.get(src.name, {})  # source lines the txt lacks

        pool = defaultdict(deque)
        for entry_number, entry in enumerate(entries):
            parts = split_entry(entry)
            if parts is None:
                sys.exit(f"{txt.name}: line without {SEP}: {entry!r}")
            pool[parts[0]].append((entry_number, parts[1]))

        out = list(head)
        reordered = []
        for position, line in enumerate(source_lines):
            en, ja = columns(src.name, line)
            queue = pool.get(en)
            if queue:
                entry_number, text = queue.popleft()
                if entry_number != position:
                    reordered.append((en, entry_number, position))
            elif en in extra_lines:
                print(
                    f"warning: {txt.name}: no entry for source line {en!r}, translated from EXTRA_TRANSLATIONS",
                    file=sys.stderr,
                )
                text = extra_lines[en]
            else:
                print(
                    f"warning: {txt.name}: no entry for source line {en!r}, kept in English",
                    file=sys.stderr,
                )
                text = ""
            text = text or en  # not translated yet: keep the English
            out.append(text if ja is None else f"{text}|{ja}")

        for en, queue in pool.items():  # entries the source no longer has
            for _, ru in queue:
                if ru:
                    print(
                        f"warning: {txt.name}: translation of {en!r} dropped, not in {src.name}",
                        file=sys.stderr,
                    )

        if reordered:
            en, entry_number, position = reordered[0]
            print(
                f"warning: {txt.name}: {len(reordered)} of {len(source_lines)} lines are in a different order from "
                f"{src.name} (first: {en!r} is on txt line {entry_number + 1}, expected line {position + 1})",
                file=sys.stderr,
            )

        target = OUTPUT / src.name
        write_lines(target, out)
        # Untranslated output equals the original: recording it would make the game's own file look like pipeline output.
        if target.read_bytes() != src.read_bytes():
            common.record_produced(target)
        print(f"{src.name}: written")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("carry", "update the txt files from the untranslated .jn files"),
        ("apply", "write the translated .jn files to output/language/engLanguage"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--source",
            type=pathlib.Path,
            default=SOURCE,
            help="folder with the untranslated .jn files (default: the Steam English folder)",
        )
    args = parser.parse_args()

    if args.command == "carry":
        carry(args.source)
    else:
        apply(args.source)


if __name__ == "__main__":
    main()
