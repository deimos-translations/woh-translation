"""Writes a World of Horror `save.ito` with every unlock set the way the game itself stores it.

The save is the plain-text INI `%LOCALAPPDATA%\\wohgame\\save.ito` (scr_systemload -> scr_openini("save.ito") -> ini_read_*).
Stored values (see NOTES.md, "Save file"):
- [achievement]: every cell holds its own 4-digit code, written by endgame_check_achievements when a run ends ("yes" is only the in-run
  marker; the unlock checks compare against the code). `save_codes.json` is that table, 121 "row,col" cells + the plain keys 1..26.
- [pantheon]: 001..005 hold the codes endgame_check_pantheon writes.
- [events], [enemies], [mysteries]: the game stores the string "yes".
Everything else in an existing file ([options], [town], [city], [challenges], ...) is kept as it is.

    python -I re/save_cheat.py [existing save.ito] <output file>

The key lists come from scr_systemload of the analysed build; after a game update re-check them (NOTES.md, "After a game update").
"""
import json
import sys
from pathlib import Path

PANTHEON = {"001": "478423", "002": "234645", "003": "195573", "004": "593821", "005": "555039"}
MYSTERIES = "abnormal_a abnormal_b abnormal_c botany_a botany_b botany_c botany_d bulletin_a bulletin_b bulletin_c clan_a clan_b clan_c clan_d coma_a coma_b coma_c crimson_a crimson_b crimson_c eels_a eels_b eels_c festival_a festival_b festival_c forest_a forest_b forest_c hospital_a hospital_b hospital_c household_a household_b household_c janitor_a janitor_b janitor_c janitor_d janitor_e jeane_a jeane_b loggers_a loggers_b loggers_c loggers_d nails_a nails_b nails_c painting_a painting_b painting_c pax02_a pax02_b pax02_c pax03_a pax03_b pax03_c pax_a pax_b pax_c ramen_a ramen_b sailor_a sailor_b sailor_c school_a school_b school_c school_d seaside_a seaside_b seaside_c teacher_a teacher_b trip_a trip_b whisper_a whisper_b whisper_c".split()


def unlocked_values():
    codes = json.loads((Path(__file__).parent / "save_codes.json").read_text())
    return {
        "achievement": codes,
        "pantheon": PANTHEON,
        "mysteries": dict.fromkeys(MYSTERIES, "yes"),
        "enemies": dict.fromkeys((f"{num:03}" for num in range(1, 121)), "yes"),
        "events": dict.fromkeys((f"{num:03}" for num in range(1, 251)), "yes"),
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
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sections = read_sections(sys.argv[1]) if len(sys.argv) == 3 else {}
    counts = {}
    for name, keys in unlocked_values().items():
        body = sections.setdefault(name, {})
        body.update({key: f'"{val}"' for key, val in keys.items()})
        counts[name] = len(keys)
    with open(sys.argv[-1], "w", encoding="utf-8", newline="\r\n") as out:
        for name, body in sections.items():
            out.write(f"[{name}]\n")
            out.writelines(f"{key}={val}\n" for key, val in body.items())
    print("wrote", sys.argv[-1], counts)


main()
