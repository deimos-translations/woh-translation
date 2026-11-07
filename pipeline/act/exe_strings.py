"""Создаёт или обновляет документ перевода translation/exe_strings.txt.

Использование: python -I pipeline/act/exe_strings.py <targets.tsv> [document]   (обычно `woh.py sync`)

Одна строка на каждую уникальную строку: `source|translation`. Управляющие символы экранируются как `\\`, `\r`, `\n`, `\t`,
а `#` — собственный перенос строки игры, поэтому оставляйте оба как есть. Пустой перевод оставляет строку нетронутой.
Первые четыре строки (`DOOM`, `STA`, `REA`, `ALL`) — подписи урона в бою: то, что показывают боевые экраны для этого
типа урона. Это не копии строк в exe, поэтому пустая строка оставляет английский текст.
Существующие переводы сохраняются, поэтому команду можно запускать повторно после изменения списка целей. Переведённая строка, которой нет в списке целей (нет копии в коде этой сборки), тоже сохраняется и сообщается; удаляются только пустые строки. Переводы применяются, когда игра рисует текст (`woh.py build`), поэтому значения, которые сравнивает логика игры, никогда не меняются; добавьте `--literal`, чтобы также заменить собственные копии текстов exe, которые код не сравнивает.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common
from common import LABEL_KEYS, SEPARATOR


def main(targets, document):
    sources = dict.fromkeys(LABEL_KEYS)
    with open(targets, encoding="utf-8", newline="") as file:
        for line in file:
            sources[line.rstrip("\n").split("\t")[1]] = None
    existing = {}
    if document.exists():
        with open(document, encoding="utf-8", newline="") as file:
            for line in file:
                source, _, translation = line.rstrip("\n").partition(SEPARATOR)
                existing[source] = translation
    kept = [text for text, translation in existing.items() if translation and text not in sources]
    for text in kept:
        sources[text] = None
    with open(document, "w", encoding="utf-8", newline="") as out:
        for text in sources:
            out.write(f"{text}{SEPARATOR}{existing.get(text, '')}\n")
    print(f"{len(sources)} strings, {sum(1 for text in sources if existing.get(text))} already translated, {len(kept)} kept without a code copy -> {document}")
    for text in kept:
        print(f"  kept, no code copy: {text!a} = {existing[text]!a}")


if __name__ == "__main__":
    main(sys.argv[1], pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else common.TRANSLATION / "exe_strings.txt")
