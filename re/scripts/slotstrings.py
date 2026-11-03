"""Slot -> literal map from the startup initializers: `lea rcx,[slot]; lea rdx,[lit]; call 1420d8090` (either lea order).
`python -I slotstrings.py <exe> <out.tsv> [call-target-VA]`; the target is auto-detected (most common call target of that pattern) when omitted.
Also usable as a module (load())."""
import re, struct, sys
BASE = 0x140000000
def load(path, target=None):
    d = open(path, 'rb').read()
    pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe + 6)[0]; so = struct.unpack_from('<H', d, pe + 20)[0]
    secs = [struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]
    def off(va):
        r = va - BASE
        for vs, sva, rs, rp in secs:
            if sva <= r < sva + max(vs, rs): return rp + r - sva
    text = secs[0]; code = d[text[3]:text[3] + text[2]]; tva = BASE + text[1]
    out = {}
    pat = re.compile(rb'\x48\x8d([\x0d\x15])(....)\x48\x8d([\x0d\x15])(....)\xe8(....)', re.S)
    if target is None:
        calls = {}
        for m in pat.finditer(code):
            s = struct.unpack('<i', m.group(5))[0] + tva + m.start() + 19
            calls[s] = calls.get(s, 0) + 1
        target = max(calls, key=calls.get)
    for m in pat.finditer(code):
        if m.group(1) == m.group(3): continue
        a = tva + m.start(); s = struct.unpack('<i', m.group(5))[0] + a + 19
        if s != target: continue
        r1 = struct.unpack('<i', m.group(2))[0] + a + 7; r2 = struct.unpack('<i', m.group(4))[0] + a + 14
        slot, lit = (r1, r2) if m.group(1) == b'\x0d' else (r2, r1)
        o = off(lit)
        if o is None: continue
        out[slot] = d[o:d.index(b'\0', o)].decode('utf-8', 'replace')
    return out
if __name__ == '__main__':
    m = load(sys.argv[1], int(sys.argv[3], 16) if len(sys.argv) > 3 else None)
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        for k in sorted(m): f.write(f'{k:x}\t{m[k]!r}\n')
    print(len(m), 'slots')
