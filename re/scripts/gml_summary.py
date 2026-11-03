"""One-screen summary of a decompiled GML function (a .named.c from slotnames.py): script/object name, the globals and builtins it names, the
literal strings, and every compare/assign against a constant, with doubles decoded. Meant for skimming big event/script bodies.
`python -I gml_summary.py <file.named.c> [max_lines]`"""
import re, struct, sys
t = open(sys.argv[1], encoding='utf-8').read()
name = re.search(r'"(gml_\w+)"', t)
print('#', name.group(1) if name else sys.argv[1], '(%d lines)' % t.count('\n'))
vars_, strs = [], []
for m in re.finditer(r"DAT_[0-9a-f]+/\*([^*]+)\*/", t):
    n = m.group(1)
    (strs if n[0] in "'\"" else vars_).append(n)
vars_ = list(dict.fromkeys(vars_)); strs = list(dict.fromkeys(strs))
print('names  :', ', '.join(vars_))
print('strings:', ' | '.join(strs)[:1500])
def dec(v): return struct.unpack('<d', struct.pack('<Q', v))[0]
consts = []
for m in re.finditer(r"= (0x[34][0-9a-f]{15});", t):
    d = dec(int(m.group(1), 16))
    if d == int(d) and abs(d) < 1e7: consts.append(int(d))
    else: consts.append(round(d, 4))
print('doubles:', ' '.join(str(c) for c in dict.fromkeys(consts))[:600])
