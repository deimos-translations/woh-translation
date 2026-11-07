"""Хранит translation/*.txt как источник перевода и создаёт из него .jn файлы.

Формат .jn: одна строка "English|Japanese" на каждую строку текста (woh_ui.jn также начинается со строки-заголовка "English|Japanese").
woh_ver.jn — простой текст без японской колонки: его английский текст — часть до первого "|" (первая строка повторяет английский после "|", это не сохраняется).
Формат txt: одна строка "<eng>|<rus>" на каждую строку .jn с текстом (заголовок пропущен), в том же порядке. Пустой <rus> записывается как пустая строка.
Разделитель — первый "|" в строке.

carry: перезаписать каждый txt из непереведённых .jn файлов в --source. Каждая новая английская строка получает русский текст
  строки txt с тем же английским. Английские строки, которых больше нет в игре, сообщаются как удалённые.
apply: записать каждый переведённый .jn в output/language/engLanguage. Японская колонка и заголовок берутся из .jn файлов --source.
  Строки сопоставляются по английскому тексту. Завершается с ошибкой, если английского текста из txt нет в источнике (сначала запустите carry);
  выдаёт предупреждение, если строки txt идут в другом порядке, чем в .jn файле.

Исходные файлы должны быть оригиналами игры: файлы, записанные этим конвейером, отклоняются.

Использование (обычно `woh.py sync` и `woh.py build --no-exe --no-sprites`):
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
import common

SEP = common.SEPARATOR
LANGUAGE = common.TRANSLATION
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
    for src in sorted(source.glob("*.jn")):
        common.require_pristine(src)
        txt = LANGUAGE / src.with_suffix(".txt").name
        if not txt.exists():
            sys.exit(f"{txt.name} is missing: run carry")
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
    for name, help_text in (("carry", "обновить txt файлы из непереведённых .jn файлов"),
                            ("apply", "записать переведённые .jn файлы в output/language/engLanguage")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--source", type=pathlib.Path, default=SOURCE,
                             help="папка с непереведёнными .jn файлами (по умолчанию английская папка Steam)")
    args = parser.parse_args()

    if args.command == "carry":
        carry(args.source)
    else:
        apply(args.source)


if __name__ == "__main__":
    main()
