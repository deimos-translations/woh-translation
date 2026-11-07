"""Сверяет документ перевода translation/exe_strings.txt со списком целей этой сборки и пишет отчёт о новых текстах exe.

Использование: python -I pipeline/act/exe_strings.py <targets.tsv> <candidates.txt> [document]   (обычно `woh.py sync`)

Документ ведётся вручную и содержит только переводимые строки: sync его не меняет. Тексты из списка целей, которых нет в документе, пишутся в
candidates.txt в том же формате (`source|`), чтобы переносить нужные строки в документ руками (после обновления игры или для найденных текстов).

Одна строка на каждую уникальную строку: `source|translation`. Перенос строки игры (CRLF) пишется как `\\n`, голый LF как `\\l`,
голый CR как `\\r`; `\\\\` и `\\t` экранируются; `#` — собственный перенос строки игры, поэтому оставляйте его как есть.
Первые четыре строки (`DOOM`, `STA`, `REA`, `ALL`) — подписи урона в бою: то, что показывают боевые экраны для этого
типа урона. Это не копии строк в exe, поэтому пустая строка оставляет английский текст.
Переводы применяются, когда игра рисует текст (`woh.py build`), поэтому значения, которые сравнивает логика игры, никогда не меняются.
Строка с `!` в начале (`!source|translation`) также заменяет собственные копии текста в exe: нужно для текста, который склеивается до отрисовки
(`rolled`, `dmg / `). Ставьте `!` только после проверки: если код использует текст как ключ, игра ломается. Сборка отказывается патчить помеченную
строку, которую анализ считает логической (usage.tsv: logic). Источник, который сам начинается с `!`, пишется как `\\!`.
Sync сообщает строки документа без копии в коде этой сборки и строки без перевода.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # -I does not add the script directory
import common
from common import LABEL_KEYS, LITERAL_MARK, SEPARATOR


def main(targets, candidates, document):
    entries = {}  # escaped source -> translation
    with open(document, encoding="utf-8", newline="") as file:
        for line in file.read().split("\n"):
            if line:
                _literal, source, _, translation = common.parse_entry(line)
                entries[common.escape(common.unescape(source))] = translation  # `\!` and `!` name the same source
    found, new = set(), []
    with open(targets, encoding="utf-8", newline="") as file:
        for line in file.read().split("\n"):
            if line:
                text = line.split("\t")[1]
                if text in found:
                    continue
                found.add(text)
                if text not in entries:
                    new.append(text)
    with open(candidates, "w", encoding="utf-8", newline="") as out:
        for text in new:
            out.write(f"{'\\' if text.startswith(LITERAL_MARK) else ''}{text}{SEPARATOR}\n")
    print(f"{len(entries)} entries in {document.name}, {len(new)} exe texts not in it -> {pathlib.Path(candidates).resolve()}")
    for text, translation in entries.items():
        if text not in found and text not in LABEL_KEYS:
            print(f"  no code copy in this build: {text}")
        if not translation:
            print(f"  no translation: {text}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else common.TRANSLATION / "exe_strings.txt")
