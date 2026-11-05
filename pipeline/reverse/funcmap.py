"""Function VA -> GML name: `python -I funcmap.py <exe> <out.tsv>`
The runtime reads a table in .data of (name pointer, function, data pointer) triples, 24 bytes each; the name is a `gml_Object_<obj>_<Event>_<n>` or
`gml_Script_<name>` string in .rdata. We find every qword that points at such a string and take the qword right after it as the function."""
import re, struct, sys

exe, out = sys.argv[1:3]
d = open(exe, 'rb').read()
B = 0x140000000
pe = struct.unpack_from('<I', d, 0x3c)[0]
n = struct.unpack_from('<H', d, pe + 6)[0]
so = struct.unpack_from('<H', d, pe + 20)[0]
secs = [(d[pe + 24 + so + i * 40:pe + 24 + so + i * 40 + 8].rstrip(b'\0').decode(),) + struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]


def va(off):
    for _name, vsize, sva, rsize, rptr in secs:
        if rptr <= off < rptr + rsize:
            return B + sva + off - rptr
    return None


def off_of(vaddr):
    rel = vaddr - B
    for _name, vsize, sva, rsize, rptr in secs:
        if sva <= rel < sva + min(vsize, rsize):
            return rptr + rel - sva
    return None


NAME = re.compile(rb'gml_(?:Object|Script|GlobalScript|RoomCC|Room)_[A-Za-z0-9_]+\0')
data = [s for s in secs if s[0] == '.data'][0]
text = [s for s in secs if s[0] == '.text'][0]
image_end = B + max(s[2] + s[1] for s in secs)
start, size = data[4], data[3]
func = {}
names = 0
for off in range(start, start + size - 16, 8):
    ptr = struct.unpack_from('<Q', d, off)[0]
    if not (B < ptr < image_end):
        continue
    so_ = off_of(ptr)
    if so_ is None:
        continue
    m = NAME.match(d, so_)  # read the string at the pointer: pooled strings can share bytes, so a scan of the whole image misses some
    if m is None:
        continue
    names += 1
    fn = struct.unpack_from('<Q', d, off + 8)[0]
    if B + text[2] <= fn < B + text[2] + text[1]:
        func.setdefault(fn, m.group(0)[:-1].decode())
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    for fn, name in sorted(func.items()):
        f.write('%x\t%s\n' % (fn, name))
print(len(func), 'functions named,', names, 'name pointers')
