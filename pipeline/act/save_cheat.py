"""Записывает World of Horror `save.ito` со всеми разблокировками, установленными так, как их сохраняет сама игра.

Сохранение — это простой текстовый INI `%LOCALAPPDATA%\\wohgame\\save.ito` (scr_systemload -> scr_openini("save.ito") -> ini_read_*).
Сохраняемые значения (см. pipeline/README.md, "Save file"):
- [achievement]: каждая ячейка хранит свой 4-значный код, который записывает endgame_check_achievements при завершении забега ("yes" — лишь
  маркер текущего забега; проверки разблокировок сравнивают с кодом). Этап save_codes создаёт эту таблицу: 121 ячейка "row,col" + простые ключи 1..26.
- [pantheon]: 001..005 хранят коды, которые записывает endgame_check_pantheon.
- [events], [enemies], [mysteries]: игра хранит строку "yes".
Всё остальное в существующем файле ([options], [town], [city], [challenges], ...) сохраняется как есть.

    woh.py save [существующий save.ito] <выходной файл>
    python -I pipeline/act/save_cheat.py <save_codes.json> <save_keys.json> [существующий save.ito] <выходной файл>

Списки ключей берутся из проанализированной сборки (этап save_keys), кроме счётчика [events]: перепроверьте его после обновления игры (pipeline/README.md, "Save file").
"""
import json
import sys
from pathlib import Path

EVENT_COUNT = 250  # scr_systemsave builds these keys in a loop, so the count is not a literal the pipeline can read


def unlocked_values(codes_path, keys_path):
    codes = json.loads(Path(codes_path).read_text())
    keys = json.loads(Path(keys_path).read_text())
    return {
        "achievement": codes,
        "pantheon": keys["pantheon"],
        "mysteries": dict.fromkeys(keys["mysteries"], "yes"),
        "enemies": dict.fromkeys(keys["enemies"], "yes"),
        "events": dict.fromkeys((f"{num:03}" for num in range(1, EVENT_COUNT + 1)), "yes"),
    }


def read_sections(path):
    """INI -> {section: {key: raw value text}} in file order; GameMaker writes `key="value"`."""
    out, cur = {}, None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = out.setdefault(line[1:-1], {})
        elif cur is not None and "=" in line:
            key, val = line.split("=", 1)
            cur[key] = val
    return out


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    sections = read_sections(sys.argv[3]) if len(sys.argv) == 5 else {}
    counts = {}
    for name, keys in unlocked_values(sys.argv[1], sys.argv[2]).items():
        body = sections.setdefault(name, {})
        body.update({key: f'"{val}"' for key, val in keys.items()})
        counts[name] = len(keys)
    with open(sys.argv[-1], "w", encoding="utf-8", newline="\r\n") as out:
        for name, body in sections.items():
            out.write(f"[{name}]\n")
            out.writelines(f"{key}={val}\n" for key, val in body.items())
    print("wrote", sys.argv[-1], counts)


main()
