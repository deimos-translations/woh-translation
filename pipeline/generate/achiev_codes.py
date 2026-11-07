"""Extracts the achievement codes by cell from the decompiled `endgame_check_achievements` (the .named.c made by slotnames.py).
`python -I achiev_codes.py <file.named.c> <out.json>`

The pattern in that function: `p = idxset(base, row); c = idxset(p, col); ... assign(c, &DAT_x/*'code'*/)`. Codes are kept, "yes" is the current-run marker.
Helper names differ between builds, so they are matched by shape. Keys: "row,col" (two levels) or "n" (one level)."""

import json
import pathlib
import re
import sys

with pathlib.Path(sys.argv[1]).open(encoding="utf-8") as file:
    lines = [ln for ln in file if ln.strip()]
defs, cells = {}, {}
for ln in lines:
    m = re.search(
        r"(\w+) = (?:\(\w+ \*+\))?FUN_[0-9a-f]+\((\w+),(0x[0-9a-f]+|\d+)\);", ln
    )
    if m:
        defs[m.group(1)] = (m.group(2), int(m.group(3), 0))
    m = re.search(r"FUN_[0-9a-f]+\((\w+),&DAT_[0-9a-f]+/\*'(\d+)'\*/\)", ln)
    if m and m.group(1) in defs:
        path, cur, seen = [], m.group(1), set()
        while (
            cur in defs and cur not in seen
        ):  # a reused name points to itself: stop instead of looping forever
            seen.add(cur)
            cur, idx = defs[cur]
            path.append(idx)
        cells[",".join(map(str, reversed(path)))] = m.group(2)
cells = dict(
    sorted(
        cells.items(),
        key=lambda kv: (kv[0].count(","), [int(x) for x in kv[0].split(",")]),
    )
)
with pathlib.Path(sys.argv[2]).open("w") as out:
    json.dump(cells, out, indent=1)
print(len(cells), "cells")
