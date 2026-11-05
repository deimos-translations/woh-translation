"""The save keys the unlocks need, from the exe: `python -I save_keys.py <exe> <funcmap.tsv> <ini_calls.txt> <save_keys.json>`

ini_calls.txt is inicalls.py on scr_systemsave, whose ini_write_string calls name every key of these sections (the [events] keys are built
in a loop, so save_cheat.py keeps their count). The pantheon codes are the 6-digit string literals of endgame_check_pantheon, in order:
pantheon 001..005."""
import json
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reverse"))  # -I does not add the script directory
import slotstrings  # noqa: E402

BASE = 0x140000000
PANTHEON_CODES = 5


def function_body(data, start):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count, optional = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    sections = {}
    for index in range(count):
        header = pe + 24 + optional + 40 * index
        sections[data[header:header + 8].rstrip(b"\0")] = struct.unpack_from("<IIII", data, header + 8)
    _, _, pdata_size, pdata = sections[b".pdata"]
    for at in range(pdata, pdata + pdata_size - 11, 12):
        begin, end = struct.unpack_from("<II", data, at)
        if BASE + begin == start:
            _, rva, _, raw = sections[b".text"]
            return data[raw + begin - rva:raw + end - rva]
    sys.exit(f"no unwind record for function {start:#x}")


def pantheon_codes(exe_path, start):
    data = open(exe_path, "rb").read()
    literals = slotstrings.load(exe_path)
    codes = []
    for match in re.finditer(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d](....)", function_body(data, start), re.S):
        text = literals.get(start + match.end() + struct.unpack_from("<i", match.group(1))[0], "")
        if re.fullmatch(r"\d{6}", text) and text not in codes:
            codes.append(text)
    if len(codes) != PANTHEON_CODES:
        sys.exit(f"endgame_check_pantheon: expected {PANTHEON_CODES} 6-digit codes, found {codes}")
    return codes


def main(exe_path, funcmap_path, ini_calls_path, out_path):
    pantheon = [int(line.split("\t")[0], 16) for line in open(funcmap_path, encoding="utf-8") if line.rstrip("\n").endswith("\tgml_Script_endgame_check_pantheon")]
    if len(pantheon) != 1:
        sys.exit(f"gml_Script_endgame_check_pantheon: found {pantheon}")
    keys = {"mysteries": [], "enemies": []}
    for line in open(ini_calls_path, encoding="utf-8"):
        match = re.match(r"ini_write_string \[.*'(\w+)', '([^']+)'\]$", line.rstrip())
        if match and match.group(1) in keys and match.group(2) not in keys[match.group(1)]:
            keys[match.group(1)].append(match.group(2))
    for section, found in keys.items():
        if not found:
            sys.exit(f"scr_systemsave: no keys found for section {section}")
    keys["pantheon"] = {f"{number:03}": code for number, code in enumerate(pantheon_codes(exe_path, pantheon[0]), 1)}
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        json.dump(keys, out, indent=1)
    print({section: len(found) for section, found in keys.items()})


if __name__ == "__main__":
    main(*sys.argv[1:5])
