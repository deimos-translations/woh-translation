"""Классифицирует строки targets.tsv по тому, что код с ними делает.

Использование: python -I pipeline/generate/classify_usage.py <targets.tsv> <uses.tsv> <VA функции сравнения, hex> <usage.tsv>

uses.tsv — это выход `.uses.tsv` от StringUses.java. Функция сравнения — та, что содержит строку "Cannot compare unset
variables" (её находит resolve_helpers.py). Текст относится к `logic`, когда значение передаётся в функцию сравнения в пределах первых шести
вызовов после загрузки, то есть код проверяет его против чего-то (`if (x == "PREP")`). `logic` означает, что перевод должен оставаться
согласованным со всеми другими местами, которые создают или проверяют это значение. Другой класс, `not-compared-nearby`, не доказывает безопасность:
значение может быть сохранено и проверено в другом скрипте.
"""
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
import common


def classify(stat):
    return "logic" if stat["compares"] else "not-compared-nearby" if stat["uses"] else "no-use-found"


def main(targets_path, uses_path, compare_va, usage_path):
    texts = {}
    with open(targets_path, encoding="utf-8", newline="") as file:
        for line in file:
            va, text = line.rstrip("\n").split("\t")
            texts[va] = common.unescape(text)
    stats = collections.OrderedDict((text, {"copies": 0, "uses": 0, "compares": 0, "scripts": set()}) for text in texts.values())
    for text in texts.values():
        stats[text]["copies"] += 1
    with open(uses_path, encoding="utf-8") as file:
        for line in file:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 6 or cols[0] not in texts:
                continue
            stat = stats[texts[cols[0]]]
            stat["uses"] += 1
            if compare_va in [call for call in cols[5].split(",") if call][:6]:
                stat["compares"] += 1
            stat["scripts"].add(cols[4] or "?")
    with open(usage_path, "w", encoding="utf-8", newline="") as out:
        out.write("class\tcopies\tuses\tcompares\tscripts\ttext\n")
        for text, stat in stats.items():
            scripts = ",".join(sorted(stat["scripts"]))[:100]
            out.write(f"{classify(stat)}\t{stat['copies']}\t{stat['uses']}\t{stat['compares']}\t{scripts}\t{text!a}\n")
    print(dict(collections.Counter(classify(stat) for stat in stats.values())))


if __name__ == "__main__":
    main(*sys.argv[1:5])
