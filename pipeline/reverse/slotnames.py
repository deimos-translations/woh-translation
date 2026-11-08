"""Replaces built-in function id slots in decompiled .c files with names: `python -I slotnames.py <exe> <file.c>...` (writes <file>.named.c).
A built-in call: FUN_1420df500(self,other,&ret,argc,CONCAT44(x,DAT_slot),args); the slot's name pointer is 8 bytes BEFORE it."""

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common
import slotstrings

BASE = 0x140000000
LIT = slotstrings.load(sys.argv[1])
d = pathlib.Path(sys.argv[1]).read_bytes()
secs = common.pe_sections(d)


def rd(va, ln):
    r = va - BASE
    for vs, sva, rs, rp in secs.values():
        if sva <= r < sva + max(vs, rs):
            return d[rp + r - sva : rp + r - sva + ln]
    return None


def name(slot):
    b = rd(slot - 8, 8)
    if not b:
        return None
    q = struct.unpack("<Q", b)[0]
    s = rd(q, 64) if BASE <= q < 0x150000000 else None
    if not s:
        return None
    s = s.split(b"\0")[0]
    return (
        s.decode("latin1") if re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_]{2,60}", s) else None
    )


def sub(m):
    va = int(m.group(1), 16)
    if va in LIT:
        return f"{m.group(0)}/*{LIT[va]!r}*/"
    nm = name(va)
    return f"{m.group(0)}/*{nm}*/" if nm else m.group(0)


for f in sys.argv[2:]:
    t = pathlib.Path(f).read_text(encoding="utf-8")
    pathlib.Path(f[:-2] + ".named.c").write_text(
        re.sub(r"DAT_(1[0-9a-f]{8})(?=[);,])", sub, t), encoding="utf-8"
    )
