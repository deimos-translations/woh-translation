"""Annotate a DumpAsm text file: builtin-id loads -> name, string-slot leas -> literal. `python -I annotasm.py <exe> <in.asm> <out.asm>`"""
import re, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slotstrings
exe = sys.argv[1]; d = open(exe, 'rb').read(); B = 0x140000000
pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe + 6)[0]; so = struct.unpack_from('<H', d, pe + 20)[0]
secs = [struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]
def off(va):
    r = va - B
    for vs, sva, rs, rp in secs:
        if sva <= r < sva + max(vs, rs): return rp + r - sva
LIT = slotstrings.load(exe)
def bname(slot):
    o = off(slot - 8)
    if o is None or o + 8 > len(d): return None
    q = struct.unpack_from('<Q', d, o)[0]
    if not 0x140000000 <= q < 0x150000000: return None
    s = d[off(q):off(q) + 64].split(b'\0')[0]
    return s.decode('latin1') if re.fullmatch(rb'[A-Za-z_]\w{2,60}', s) else None
with open(sys.argv[2]) as fi, open(sys.argv[3], 'w') as fo:
    for ln in fi:
        m = re.search(r'\[0x(14[0-9a-f]{7})\]', ln)
        if m:
            v = int(m.group(1), 16)
            if v in LIT: ln = ln.rstrip('\n') + f'   ; {LIT[v]!r}\n'
            elif 'MOV' in ln and 'dword' in ln and (nm := bname(v)): ln = ln.rstrip('\n') + f'   ; <{nm}>\n'
        fo.write(ln)
