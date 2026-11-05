"""Keep translation/language/engLanguage/*.txt as the translation source, and generate .jn files from it.

.jn format: one "English|Japanese" line per string (woh_ui.jn also starts with a header line "English|Japanese").
woh_ver.jn is plain text with no Japanese column: its English is the part before the first "|" (line 1 repeats the English after the "|", which is not kept).
txt format: one "<eng>|<rus>" line per .jn string line (header omitted), same order. An empty <rus> is written as an empty string.
The separator is the first "|" in the line.

carry: rewrite each txt from the untranslated .jn files in --source. Each new English line takes the Russian of the
  txt line with the same English. English that is no longer in the game is reported as dropped.
apply: write each translated .jn into output/language/engLanguage. The Japanese column and header come from
  the --source .jn files. Lines are matched by English. Fails if a txt English is missing from the source (run carry first);
  warns if the txt lines are in a different order from the .jn file.

The source files must be the game's originals: files this pipeline wrote are refused.

Usage (normally `woh.py sync` and `woh.py text`):
  python -I pipeline/act/woh_txt.py carry [--source DIR]
  python -I pipeline/act/woh_txt.py apply [--source DIR]
"""

import argparse
import pathlib
import sys
from collections import defaultdict, deque

HEADER = "English|Japanese"
PLAIN_TEXT = {"woh_ver.jn"}
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common  # noqa: E402

SEP = common.SEPARATOR
LANGUAGE = common.TRANSLATION / "language" / "engLanguage"
OUTPUT = common.OUTPUT / common.LANGUAGE
SOURCE = common.STEAM / common.LANGUAGE


def read_lines(path):
    lines = path.read_bytes().decode("utf-8").split("\r\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def split_header(lines):
    head = lines[:1] if lines and lines[0] == HEADER else []
    return head, lines[len(head):]


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\r\n".join(lines).encode("utf-8"))


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
        for entry in (read_lines(txt) if txt.exists() else []):
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
        print(f"{txt.name}: {len(out)} lines, {unmatched} without a match, {dropped} translations dropped")


def apply(source):
    for txt in sorted(LANGUAGE.glob("*.txt")):
        src = source / txt.with_suffix(".jn").name
        common.require_pristine(src)
        head, source_lines = split_header(read_lines(src))
        entries = read_lines(txt)
        if len(entries) != len(source_lines):
            sys.exit(f"{txt.name}: {len(entries)} entries, but {src.name} has {len(source_lines)} lines; run carry")

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
            if not queue:
                sys.exit(f"{txt.name}: no entry for source line {en!r}; run carry")
            entry_number, text = queue.popleft()
            if entry_number != position:
                reordered.append((en, entry_number, position))
            out.append(text if ja is None else f"{text}|{ja}")

        if reordered:
            en, entry_number, position = reordered[0]
            print(f"warning: {txt.name}: {len(reordered)} of {len(source_lines)} lines are in a different order from "
                  f"{src.name} (first: {en!r} is on txt line {entry_number + 1}, expected line {position + 1})",
                  file=sys.stderr)

        write_lines(OUTPUT / src.name, out)
        common.record_produced(OUTPUT / src.name)
        print(f"{src.name}: written")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("carry", "update the txt files from the untranslated .jn files"),
                            ("apply", "write translated .jn files into output/language/engLanguage")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--source", type=pathlib.Path, default=SOURCE,
                             help="folder with the untranslated .jn files (default: Steam English folder)")
    args = parser.parse_args()

    if args.command == "carry":
        carry(args.source)
    else:
        apply(args.source)


if __name__ == "__main__":
    main()
