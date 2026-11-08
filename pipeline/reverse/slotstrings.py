"""Slot -> literal map from the startup initializers: `lea rcx,[slot]; lea rdx,[lit]; call 1420d8090` (either lea order).
`python -I slotstrings.py <exe> <out.tsv> [call target VA]`; the target is detected automatically (the most frequent call target of this pattern) if not given.
Can also be used as a module (load())."""

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common

BASE = 0x140000000


def load(path, target=None, literal_addresses=False):
    d = pathlib.Path(path).read_bytes()
    secs = common.pe_sections(d)

    def off(va):
        r = va - BASE
        for vs, sva, rs, rp in secs.values():
            if sva <= r < sva + max(vs, rs):
                return rp + r - sva
        return None

    _, text_rva, text_size, text_raw = secs[".text"]
    code = d[text_raw : text_raw + text_size]
    tva = BASE + text_rva
    out = {}
    pat = re.compile(
        rb"\x48\x8d([\x0d\x15])(....)\x48\x8d([\x0d\x15])(....)\xe8(....)", re.DOTALL
    )
    if target is None:
        calls = {}
        for m in pat.finditer(code):
            s = struct.unpack("<i", m.group(5))[0] + tva + m.start() + 19
            calls[s] = calls.get(s, 0) + 1
        target = max(calls, key=calls.get)
    for m in pat.finditer(code):
        if m.group(1) == m.group(3):
            continue
        a = tva + m.start()
        s = struct.unpack("<i", m.group(5))[0] + a + 19
        if s != target:
            continue
        r1 = struct.unpack("<i", m.group(2))[0] + a + 7
        r2 = struct.unpack("<i", m.group(4))[0] + a + 14
        slot, lit = (r1, r2) if m.group(1) == b"\x0d" else (r2, r1)
        o = off(lit)
        if o is None:
            continue
        out[lit if literal_addresses else slot] = d[o : d.index(b"\0", o)].decode(
            "utf-8", "replace"
        )
    return out


if __name__ == "__main__":
    m = load(sys.argv[1], int(sys.argv[3], 16) if len(sys.argv) > 3 else None)
    with pathlib.Path(sys.argv[2]).open("w", encoding="utf-8") as f:
        f.writelines(f"{k:x}\t{m[k]!r}\n" for k in sorted(m))
    print(len(m), "slots")
