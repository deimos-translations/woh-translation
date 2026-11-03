"""Condense an annotated DumpAsm file (annotasm.py output) to the instructions that carry meaning: string/var-id/builtin annotations, calls,
branches and double constants (decoded). `python -I asmflow.py <exe> <in.ann.asm> <first line> <last line>`; prints to stdout."""
import re, struct, sys
exe = sys.argv[1]; d = open(exe, 'rb').read(); B = 0x140000000
pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe + 6)[0]; so = struct.unpack_from('<H', d, pe + 20)[0]
secs = [struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]
def off(va):
    r = va - B
    for vs, sva, rs, rp in secs:
        if sva <= r < sva + max(vs, rs): return rp + r - sva
lines = open(sys.argv[2], encoding='utf-8').read().split('\n')
a, b = int(sys.argv[3]), int(sys.argv[4])
for ln in lines[a - 1:b]:
    m = re.match(r'(\w+)\s+(.*)', ln)
    if not m: continue
    addr, rest = m.groups()
    out = None
    mm = re.search(r'MOV R\w+,0x([0-9a-f]{16})\b', rest)
    if mm:
        v = int(mm.group(1), 16)
        if 0x3f00000000000000 <= v < 0x4100000000000000 or v == 0x8000000000000000:
            out = 'dbl %g' % struct.unpack('<d', struct.pack('<Q', v))[0]
    mm = re.search(r'MOVSD (\w+),qword ptr \[0x(14[0-9a-f]{7})\]', rest)
    if mm and off(int(mm.group(2), 16)):
        out = 'dbl %g' % struct.unpack_from('<d', d, off(int(mm.group(2), 16)))[0]
    mm = re.search(r'LEA RDX,\[0x(14[0-9a-f]{7})\]', rest)
    if mm and ';' not in rest and off(int(mm.group(1), 16)):
        o = off(int(mm.group(1), 16)); v, fl, kind = struct.unpack_from('<QII', d, o)
        if kind & 0xffffff == 0 and v:
            out = 'const %g' % struct.unpack('<d', struct.pack('<Q', v))[0]
    if ';' in rest and ('; ' in rest) and 'call FUN_14000f460' not in rest:
        t = rest.split(';', 1)[1].strip()
        if t.startswith('call '): out = t
        else: out = (out + ' ' if out else '') + t
    elif rest.startswith('J') or rest.startswith('CALL'):
        out = rest
    if out: print(addr, out[:150])
