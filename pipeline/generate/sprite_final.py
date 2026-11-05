"""Final per-sprite verdict: run by woh.py from the build's cache directory, inputs are the out/ tables.

Object liveness and reach come from reach.py (out/objects_alive.tsv, out/sprite_reach.tsv): an object is live when it is placed in a room or created
with a literal id by a reachable function (const), its id is a constant in a reachable function (idconst, weak), or a same-family neighbour is live (family: ids are base + n); `@moderate` / `@loose` on a
verdict means every function with a constant-id draw call of that sprite is only reachable if such weakly-evidenced / evidence-free objects exist.
Draw mode of an object: hidden (`visible` off) | auto (no Draw event in the object or its parents, the engine draws the sprite) | self-own /
self-inherit (the Draw event that applies, own or the parent's, draws sprite_index or calls draw_self, directly or in a callee up to 3 levels) |
other-own / other-inherit (it has a Draw event that does not).

Sprite verdict:
  A / A-flow          drawn: literal id, or a draw whose id is a double constant (Flow.java)
  <tier>+drawn        a draw reads a variable that holds it (flow_solve.py)
  B-<evidence>-<mode> default sprite of a created object, with the draw mode of its best object
  B-none, B-none+var  default sprite of an object nothing creates (+var: also assigned to a sprite variable)
  C-assigned          constant stored into a specific sprite variable        C-assigned-weak  only into image/text_art-like variables
  C-coord             only arithmetic/compare                                 C-unresolved / C-noconst
  D                   no reference at all"""
import collections
import json
import re


def rows(path):
    return [l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8')][1:]


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


objs = rows('out/objects.tsv')
slots = dict(l.rstrip('\n').split('\t') for l in open('out/sprites/slots.tsv'))

# --- object liveness (reach.py: evidence room | const | idconst | const-unreachable | idconst-unreachable | none) ---
ev = collections.defaultdict(set)
for r in list(tsv('out/objects_alive.tsv'))[1:]:
    if r[3] != 'none':
        ev[int(r[0])].add(r[3])
rank = {'room': 0, 'const': 1, 'idconst': 2, 'const-weak': 3, 'family': 4, 'const-unreachable': 5, 'idconst-unreachable': 6}
reach_of = {int(r[0]): r[2] for r in list(tsv('out/sprite_reach.tsv'))[1:]}

# --- which Draw events draw the instance's own sprite ---
CONFIG = json.load(open('out/sprite_config.json'))  # build-specific addresses, resolved by woh.py
SPRITE_INDEX = CONFIG['sprite_index']
si_funcs = set()  # functions that draw `sprite_index` or call the instance-based native (draw_self)
calls = collections.defaultdict(set)
for r in tsv('out/sprites/flow.tsv'):
    # rows in blocks that are dead with debug mode off (trailing dead flag) do not count
    if r[0] == 'D' and r[8] == '0' and SPRITE_INDEX in r[5].split(','):
        si_funcs.add(r[1])
    elif r[0] == 'C' and r[4] == '0':
        calls[r[1]].add(r[2])
for r in tsv('out/sprites/sites.tsv'):
    if r[0] == CONFIG['draw_self']:
        si_funcs.add(r[2])


def reaches_si(fn, depth=3):
    frontier, seen = {fn}, {fn}
    for _ in range(depth + 1):
        if frontier & si_funcs:
            return True
        frontier = {c for f in frontier for c in calls.get(f, ()) if c not in seen}
        seen |= frontier
    return False


obj_index = {o[1]: i for i, o in enumerate(objs)}
draws_self = set()
for fn, name in tsv('out/sprites/funcmap.tsv'):
    m = re.match(r'gml_Object_(.+)_Draw_\d+$', name)
    if m and m.group(1) in obj_index and reaches_si(fn):
        draws_self.add(obj_index[m.group(1)])


def draw_owner(i):
    seen = set()
    while 0 <= i < len(objs) and i not in seen:
        if int(objs[i][6]):
            return i
        seen.add(i)
        i = int(objs[i][3])
    return None


def draw_mode(i):
    if not int(objs[i][5]):
        return 'hidden'
    owner = draw_owner(i)
    if owner is None:
        return 'auto'
    return ('self' if owner in draws_self else 'other') + ('-own' if owner == i else '-inherit')


mode_rank = {'auto': 0, 'self-own': 1, 'self-inherit': 1, 'other-own': 2, 'other-inherit': 2, 'hidden': 3}
best = collections.defaultdict(lambda: 'none')
mode = collections.defaultdict(lambda: 'hidden')
for i, o in enumerate(objs):
    if o[2] and ev[i]:
        top = min(ev[i], key=rank.get)
        if rank[top] < rank.get(best[o[2]], 9):
            best[o[2]] = top
        if mode_rank[draw_mode(i)] < mode_rank[mode[o[2]]]:
            mode[o[2]] = draw_mode(i)

# --- variable evidence ---
tierc = {int(r[0]): r for r in rows('out/sprite_tierc.tsv')}
varassign = {int(r[0]): r[3] for r in rows('out/sprite_varassign.tsv')}
flow_drawn = {int(r[0]): r[3] for r in rows('out/sprite_flow.tsv')}
coord_only = {int(r[0]): 'coordinate variable ' + r[4] for r in rows('out/sprite_coordonly.tsv')}
WEAK_VARS = {'image', 'text_art', 'custom_art', 'standing', 'chibi', 'portrait'}  # also receive counter-like loops


def var_strength(sid):
    names = {v.rsplit('x', 1)[0] for v in varassign.get(sid, '').split(',') if v}
    return 'none' if not names else 'strong' if names - WEAK_VARS else 'weak'


tally = collections.Counter()
with open('out/sprite_final.tsv', 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\tverdict\tdetail\n')
    for r in rows('out/sprite_usage.tsv'):
        sid, name, tier = int(r[0]), r[1], r[2]
        detail = varassign.get(sid, '')
        if tier == 'B':
            verdict = 'B-' + best[name] + ('' if best[name] == 'none' else '-' + mode[name])
            if best[name] == 'none' and var_strength(sid) != 'none':
                verdict = 'B-none+var'
        elif tier == 'C':
            tc = tierc.get(sid)
            strength = var_strength(sid)
            if (tc and tc[2] == 'assigned') or strength == 'strong':
                verdict = 'C-assigned'
            elif strength == 'weak':
                verdict = 'C-assigned-weak'
            elif tc:
                verdict = 'C-' + tc[2]
            else:
                verdict = 'C-noconst'
            detail = detail or (tc[8] if tc else '')
            if sid in coord_only:  # every constant goes into a draw coordinate variable (coord_only.py)
                verdict, detail = 'C-coord', coord_only[sid]
        else:
            verdict = tier
        if sid in flow_drawn and verdict != 'A':
            verdict = 'A-flow' if 'const' in flow_drawn[sid] else verdict + '+drawn'
            detail = flow_drawn[sid]
        if sid in reach_of and not verdict.startswith('A'):
            verdict = 'A-builtin'  # a constant-id draw through a builtin-path call (draw_sprite_tiled); the B/C evidence is superseded
        if reach_of.get(sid, 'strict') != 'strict':
            verdict += '@' + reach_of[sid]  # its constant-id draw calls only sit in code that is reachable at a weaker level
        tally[verdict] += 1
        f.write('%d\t%s\t%s\t%s\n' % (sid, name, verdict, detail))
print(dict(sorted(tally.items())))
