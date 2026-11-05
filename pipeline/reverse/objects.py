"""Object census from data.win: `python -I objects.py <data.win> <out.tsv>`
cols: id, name, sprite_name, parent_id (-100 = none), room_instances (count over all rooms), visible, draw_own (Draw events), draw_eff (own or inherited).
OBJT entry words: name, sprite, visible, solid, depth, persistent, uses-physics, parent, texture mask, physics block..., vertex count at word 17, then
friction/awake/kinematic and the vertices, then the event lists (15 types; type 8 = Draw). An object without a Draw event draws its sprite itself."""
import collections, struct, sys

data_win, out = sys.argv[1:3]
d = open(data_win, 'rb').read()
chunks = {}
pos = 8
while pos < len(d):
    chunks[d[pos:pos + 4].decode('latin1')] = pos + 8
    pos += 8 + struct.unpack_from('<I', d, pos + 4)[0]


def cstr(p):
    return d[p:d.index(b'\0', p)].decode('utf-8', 'replace')


def table(chunk):
    p = chunks[chunk]
    n = struct.unpack_from('<I', d, p)[0]
    return list(struct.unpack_from('<%dI' % n, d, p + 4))


sprites = [cstr(struct.unpack_from('<I', d, p)[0]) for p in table('SPRT')]
objs = []
for p in table('OBJT'):
    name = cstr(struct.unpack_from('<I', d, p)[0])
    spr, visible = struct.unpack_from('<iI', d, p + 4)
    parent = struct.unpack_from('<i', d, p + 28)[0]
    vertices = struct.unpack_from('<I', d, p + 68)[0]
    events = p + 84 + 8 * vertices
    n_types = struct.unpack_from('<I', d, events)[0]
    lists = struct.unpack_from('<%dI' % n_types, d, events + 4)
    draw = n_types > 8 and struct.unpack_from('<I', d, lists[8])[0] > 0
    objs.append((name, spr, visible, parent, draw))


def effective_draw(i):
    seen = set()
    while 0 <= i < len(objs) and i not in seen:
        if objs[i][4]:
            return True
        seen.add(i)
        i = objs[i][3]
    return False


inst = collections.Counter()
for p in table('ROOM'):
    ptr = struct.unpack_from('<I', d, p + 48)[0]  # game objects (instances) list
    n = struct.unpack_from('<I', d, ptr)[0]
    for q in struct.unpack_from('<%dI' % n, d, ptr + 4):
        inst[struct.unpack_from('<i', d, q + 8)[0]] += 1

with open(out, 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\tsprite\tparent\troom_instances\tvisible\tdraw_own\tdraw_eff\n')
    for i, (name, spr, visible, parent, draw) in enumerate(objs):
        f.write('%d\t%s\t%s\t%d\t%d\t%d\t%d\t%d\n' % (i, name, sprites[spr] if spr >= 0 else '', parent, inst[i], visible, draw, effective_draw(i)))
print(len(objs), 'objects;', sum(1 for i in range(len(objs)) if inst[i]), 'placed in rooms;', sum(1 for o in objs if o[4]), 'with a Draw event')
