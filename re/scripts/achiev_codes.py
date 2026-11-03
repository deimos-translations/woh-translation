"""Extracts the per-cell achievement codes from the decompiled `endgame_check_achievements` (a .named.c made by slotnames.py).
`python -I achiev_codes.py <file.named.c> <out.json>`
Pattern in that function: `p = idxset(base, row); c = idxset(p, col); ... assign(c, &DAT_x/*'code'*/)`. The codes are persisted, "yes" is the in-run marker.
Helper names differ per build, so they are matched by shape. Keys: "row,col" (two levels) or "n" (one level)."""
import json, re, sys
lines = [ln for ln in open(sys.argv[1], encoding='utf-8') if ln.strip()]
defs, cells = {}, {}
for ln in lines:
    m = re.search(r"(\w+) = (?:\(\w+ \*+\))?FUN_[0-9a-f]+\((\w+),(0x[0-9a-f]+|\d+)\);", ln)
    if m:
        defs[m.group(1)] = (m.group(2), int(m.group(3), 0))
    m = re.search(r"FUN_[0-9a-f]+\((\w+),&DAT_[0-9a-f]+/\*'(\d+)'\*/\)", ln)
    if m and m.group(1) in defs:
        path, cur = [], m.group(1)
        while cur in defs:
            cur, idx = defs[cur]
            path.append(idx)
        cells[','.join(map(str, reversed(path)))] = m.group(2)
cells = dict(sorted(cells.items(), key=lambda kv: (kv[0].count(','), [int(x) for x in kv[0].split(',')])))
json.dump(cells, open(sys.argv[2], 'w'), indent=1)
print(len(cells), 'cells')
