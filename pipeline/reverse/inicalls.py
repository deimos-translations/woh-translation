"""Lists built-in function calls (ini_read_*/ini_write_*) in a function with their literal arguments, from raw code (no decompiler).
`python -I inicalls.py <exe> <funcVA hex> [built-in function names...]`. Arguments = the last N `lea rdx,[literal-slot]` before each call; real numbers are shown as the double loaded via `mov rax,imm64`/`movsd`; constants without `movsd` are not tracked (printed as '#')."""

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common
import slotstrings

BASE = 0x140000000
exe, fva = sys.argv[1], int(sys.argv[2], 16)
want = set(sys.argv[3:]) or {
    "ini_read_string",
    "ini_read_real",
    "ini_write_string",
    "ini_write_real",
}
d = pathlib.Path(exe).read_bytes()
secs = common.pe_sections(d)
data_vsize, data_rva, _, _ = secs[".data"]


def off(va):
    r = va - BASE
    for vs, sva, rs, rp in secs.values():
        if sva <= r < sva + max(vs, rs):
            return rp + r - sva
    return None


LIT = slotstrings.load(exe)


def bname(slot):
    o = off(slot - 8)
    q = struct.unpack_from("<Q", d, o)[0]
    if not BASE <= q < 0x150000000:
        return None
    s = d[off(q) : off(q) + 64].split(b"\0")[0]
    return s.decode("latin1") if re.fullmatch(rb"[A-Za-z_]\w{2,60}", s) else None


# function range from .pdata
_, _, pds, pdo = secs[".pdata"]
end = None
for i in range(0, pds, 12):
    b, e, _ = struct.unpack_from("<III", d, pdo + i)
    if BASE + b == fva:
        end = BASE + e
        break
o0 = off(fva)
code = d[o0 : o0 + (end - fva)]
print("function", hex(fva), "size", len(code), file=sys.stderr)
args = []
for m in re.finditer(
    rb"\x48\x8d\x15(....)|\x48\x8d\x0d(....)|\x8b[\x05\x0d\x15](....)", code, re.DOTALL
):
    a = fva + m.start()
    if m.group(1) is not None:
        t = struct.unpack("<i", m.group(1))[0] + a + 7
        if t in LIT:
            args.append(LIT[t])
    elif m.group(2) is not None:
        t = struct.unpack("<i", m.group(2))[0] + a + 7
        if t in LIT:
            args.append(LIT[t])
    elif m.group(3) is not None:
        t = struct.unpack("<i", m.group(3))[0] + a + 6
        nm = bname(t) if BASE + data_rva <= t < BASE + data_rva + data_vsize else None
        if nm in want:
            print(nm, args[-3:])
            args = []
