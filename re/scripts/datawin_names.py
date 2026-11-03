"""Asset names from the game's data.win (GameMaker FORM container): `python -I datawin_names.py <data.win> [chunk ...]`
prints `<chunk> <index> <name>` for the asset chunks (default OBJT SCPT SPRT ROOM FONT). The index is the asset id the YYC code passes around
as a double (e.g. 1026 given to an instance/item helper). Only the names are read."""
import struct, sys
path = sys.argv[1]
want = sys.argv[2:] or ['OBJT', 'SCPT', 'SPRT', 'ROOM', 'FONT']
f = open(path, 'rb')
assert f.read(4) == b'FORM'
total = struct.unpack('<I', f.read(4))[0]
chunks = {}
pos = 8
while pos < total + 8:
    f.seek(pos); name = f.read(4).decode('latin1'); size = struct.unpack('<I', f.read(4))[0]
    chunks[name] = (pos + 8, size); pos += 8 + size
def cstr(va):
    f.seek(va); out = bytearray()
    while True:
        b = f.read(256); i = b.find(b'\0')
        if i >= 0: out += b[:i]; break
        out += b
    return out.decode('utf-8', 'replace')
for ch in want:
    if ch not in chunks: continue
    start, size = chunks[ch]; f.seek(start); count = struct.unpack('<I', f.read(4))[0]
    ptrs = struct.unpack('<%dI' % count, f.read(4 * count))
    for i, p in enumerate(ptrs):
        f.seek(p); nptr = struct.unpack('<I', f.read(4))[0]
        print(ch, i, cstr(nptr))
