"""Static sprite usage report: `python -I sprite_usage.py <data.win> <sites.tsv> <consts.tsv> <out.tsv> <sink> ...` (outputs of SpriteRefs.java).
A sprite id is the SPRT index. Tiers, strongest first:
  A  a draw_sprite* native is called with this id as a literal (`MOV EDX,imm`) - drawn unless the call is unreachable
  B  default sprite of one or more objects in data.win (OBJT) - drawn by draw_self / a missing Draw event
  C  the id only appears as a double constant in game code - candidate (may be a coordinate that equals the id)
  D  no reference found - not drawn unless its id is computed or the name is looked up at runtime
The sinks are the natives whose sprite id sits in RDX."""
import collections, struct, sys

data_win, sites, consts, out = sys.argv[1:5]
sinks = set(sys.argv[5:])
d = open(data_win, 'rb').read()
chunks = {}
pos = 8
while pos < len(d):
    chunks[d[pos:pos + 4].decode('latin1')] = pos + 8
    pos += 8 + struct.unpack_from('<I', d, pos + 4)[0]

def cstr(p):
    return d[p:d.index(b'\0', p)].decode('utf-8', 'replace')

def table(chunk):
    o = chunks[chunk]
    return struct.unpack_from('<%dI' % struct.unpack_from('<I', d, o)[0], d, o + 4)

sprites = [cstr(struct.unpack_from('<I', d, p)[0]) for p in table('SPRT')]
users = collections.defaultdict(list)
for p in table('OBJT'):
    spr = struct.unpack_from('<i', d, p + 4)[0]
    if spr >= 0: users[spr].append(cstr(struct.unpack_from('<I', d, p)[0]))

drawn = collections.defaultdict(list)  # sprite -> [function VA]
dynamic = 0
for line in open(sites):
    sink, call, func, reg, val = line.rstrip('\n').split('\t')
    if reg != 'RDX' or sink not in sinks: continue
    if val.isdigit(): drawn[int(val)].append(func)
    else: dynamic += 1
dconst = {}
for line in open(consts):
    row = line.rstrip('\n').split('\t')
    dconst[int(row[0])] = int(row[1])

tally = collections.Counter()
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\ttier\tdraw_sites\tfunctions\tobjects\tdouble_consts\n')
    for i, name in enumerate(sprites):
        tier = 'A' if i in drawn else 'B' if i in users else 'C' if dconst[i] else 'D'
        tally[tier] += 1
        funcs = sorted(set(drawn[i]))
        f.write('%d\t%s\t%s\t%d\t%s\t%s\t%d\n' % (i, name, tier, len(drawn[i]), ' '.join(funcs[:4]), ' '.join(users[i][:4]), dconst[i]))
print(dict(sorted(tally.items())), 'sprites', len(sprites), '| draw sites with a computed sprite id:', dynamic)
