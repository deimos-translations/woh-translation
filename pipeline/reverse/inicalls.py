"""List builtin calls (ini_read_*/ini_write_*) in a function with their literal arguments, from raw code (no decompiler).
`python -I inicalls.py <exe> <funcVA hex> [builtin names...]`. Arguments = the last N `lea rdx,[literal-slot]` before each call; reals show as the
double loaded by `mov rax,imm64`/`movsd`-free constants are not tracked (printed as '#')."""
import re, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slotstrings
exe, fva = sys.argv[1], int(sys.argv[2], 16)
want = set(sys.argv[3:]) or {'ini_read_string', 'ini_read_real', 'ini_write_string', 'ini_write_real'}
d = open(exe, 'rb').read(); B = 0x140000000
pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe + 6)[0]; so = struct.unpack_from('<H', d, pe + 20)[0]
secs = [struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]
names = [d[pe + 24 + so + i * 40:pe + 24 + so + i * 40 + 8].rstrip(b'\0') for i in range(n)]
data_section = secs[names.index(b'.data')]
def off(va):
    r = va - B
    for vs, sva, rs, rp in secs:
        if sva <= r < sva + max(vs, rs): return rp + r - sva
LIT = slotstrings.load(exe)
def bname(slot):
    o = off(slot - 8)
    q = struct.unpack_from('<Q', d, o)[0]
    if not 0x140000000 <= q < 0x150000000: return None
    s = d[off(q):off(q) + 64].split(b'\0')[0]
    return s.decode('latin1') if re.fullmatch(rb'[A-Za-z_]\w{2,60}', s) else None
# function range from .pdata
pd = secs[names.index(b'.pdata')]
pdo, pds = pd[3], pd[2]
end = None
for i in range(0, pds, 12):
    b, e, _ = struct.unpack_from('<III', d, pdo + i)
    if B + b == fva: end = B + e; break
o0 = off(fva); code = d[o0:o0 + (end - fva)]
print('function', hex(fva), 'size', len(code), file=sys.stderr)
args = []
for m in re.finditer(rb'\x48\x8d\x15(....)|\x48\x8d\x0d(....)|\x8b[\x05\x0d\x15](....)', code, re.S):
    a = fva + m.start()
    if m.group(1) is not None:
        t = struct.unpack('<i', m.group(1))[0] + a + 7
        if t in LIT: args.append(LIT[t])
    elif m.group(2) is not None:
        t = struct.unpack('<i', m.group(2))[0] + a + 7
        if t in LIT: args.append(LIT[t])
    elif m.group(3) is not None:
        ln = 7 if code[m.start()] == 0x48 else 6
        t = struct.unpack('<i', m.group(3))[0] + a + 6
        nm = bname(t) if B + data_section[1] <= t < B + data_section[1] + data_section[0] else None
        if nm in want:
            print(nm, args[-3:]); args = []
