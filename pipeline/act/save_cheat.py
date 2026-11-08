"""Writes a World of Horror `save.ito` with all unlocks set the way the game itself saves them.

The save is a plain-text INI `%LOCALAPPDATA%\\wohgame\\save.ito` (scr_systemload -> scr_openini("save.ito") -> ini_read_*).
Saved values (see pipeline/README.md, "Save file"):
- [achievement]: each cell stores its own 4-digit code, which endgame_check_achievements writes when a run ends ("yes" is only the
  current-run marker; the unlock checks compare against the code). The save_codes stage produces this table: 121 "row,col" cells + simple keys 1..26.
- [pantheon]: 001..005 store the codes endgame_check_pantheon writes.
- [events], [enemies], [mysteries]: the game stores the string "yes".
Everything else in an existing file ([options], [town], [city], [challenges], ...) is kept as is.

    woh.py save [existing save.ito] <output file>
    python -I pipeline/act/save_cheat.py <save_codes.json> <save_keys.json> [existing save.ito] <output file>

The key lists come from the analyzed build (the save_keys stage), except the [events] counter: recheck it after a game update (pipeline/README.md, "Save file").
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
        "events": dict.fromkeys(
            (f"{num:03}" for num in range(1, EVENT_COUNT + 1)), "yes"
        ),
    }


def read_sections(path):
    """INI -> {section: {key: raw value text}} in file order; GameMaker writes `key="value"`."""
    out, cur = {}, None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
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
    target = Path(sys.argv[-1])
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\r\n") as out:
        for name, body in sections.items():
            out.write(f"[{name}]\n")
            out.writelines(f"{key}={val}\n" for key, val in body.items())
    temporary.replace(target)  # a failed write must not destroy the existing save
    print("wrote", sys.argv[-1], counts)


main()
