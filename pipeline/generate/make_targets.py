"""Строит targets.tsv (каждую копию каждой переводимой строки, на которую ссылается код) для проанализированной сборки.

Использование: python -I pipeline/generate/make_targets.py <pool_strings.tsv> <exe_strings.txt> <patch_sites.tsv> <targets.tsv>

pool_strings.tsv создаёт ExportPoolStrings.java: каждый адрес пула строк игры, на который ссылается код, с текстом, найденным там.
Важны только адреса, на которые есть ссылки; адрес со ссылкой считается копией, даже если перед ним нет NUL (он идёт после
двоичных данных) или если он указывает внутрь более длинного литерала. Побайтовый поиск надёжно не находит ни один из этих случаев.

Переводимые тексты: источники из документа перевода, плюс каждый короткий токен из заглавных букв (`PREP`, `S.ATK`, `MAGIC`, ...) и
имя из заглавных букв в кавычках (`'HAPPY LEMON'`), кроме ключей типов урона и строк подписей, которыми patch.py занимается сам. Строки вывода:
`<hex VA>\t<escaped text>`, где `\\`, CR, LF и TAB записываются как `\\\\`, `\\r`, `\\n`, `\\t`. Тексты без ссылок в коде сообщаются.
"""
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
from common import LABEL_KEYS, SEPARATOR, unescape


def escape(text):
    return "".join({"\\": "\\\\", "\r": "\\r", "\n": "\\n", "\t": "\\t"}.get(char, char) for char in text)


def is_label_like(text):
    """Short ALL-CAPS tokens (action codes, item categories, tags) and quoted ALL-CAPS names."""
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.'\-]+", text) or re.fullmatch(r"'[A-Z][A-Z .]+'", text))


def label_literals(patch_sites_path):
    """The literals patch.py repoints itself (the label slots' Polish text); translating them here would collide."""
    return {line.split("\t")[6].rstrip("\n") for line in open(patch_sites_path, encoding="utf-8") if line.startswith("slot\t")}


def main(pool_path, document_path, patch_sites_path, targets_path):
    pool = []  # (VA, text) in address order
    with open(pool_path, encoding="utf-8", newline="") as file:
        for line in file:
            va, text, _count = line.rstrip("\n").split("\t")
            pool.append((va, unescape(text)))

    excluded = set(LABEL_KEYS) | label_literals(patch_sites_path)
    wanted = {}  # insertion-ordered set: the document's order is the order of earlier target lists
    document = pathlib.Path(document_path)
    if document.exists():
        with open(document, encoding="utf-8", newline="") as file:
            for line in file:
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
        print(f"  no code reference: {text!a}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
