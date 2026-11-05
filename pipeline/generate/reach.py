"""Reachability of the code that draws each sprite: run by woh.py from the build's cache directory, inputs are the out/ tables.

A draw call only counts if the function around it can run, and an object only counts if something that can run creates it.
  roots   events of objects that can exist (plus the events of their ancestors: inheritance / event_inherited), room code, the startup initializers
          gml_GlobalScript_*
  edges   direct calls (flow.tsv `C`), and every read of the variable slot named X by a function: a script X is called through the global variable X
          that gml_GlobalScript_X binds to the body gml_Script_X (flow.tsv `R`)
Object liveness, by how sure we are that the object can exist:
  strict    placed in a room, or created with a literal id by a function that is itself reachable (fixpoint: reachability needs live objects,
            live objects need reachable creators)
  moderate  also objects whose id appears as a constant (call argument or stored value) in a function that is reachable at that level (id tables;
            fixpoint again; collisions with plain numbers are possible)
  loose     every object
Family propagation (moderate): an object whose neighbours in id order and name prefix are live counts as creatable (ids built as base + n).
Debug mode is assumed off (`debug`, `god_debug` read as 0): Flow.java decides the branches that test them, drops the call edges, draws, writes,
creation sites and reads inside the blocks that become unreachable, and the event handler that sets the flag is not a root.
A sprite's `reach` is the lowest level at which a function holding one of its constant-id draw calls is reachable (none = only in code that cannot run).
Not modelled: conditions (`if (debug)`), calls through variables/methods other than script names, `event_perform` into objects of another kind,
variable-id creation (101 sites) -- those are why `moderate` exists.
Outputs: out/func_reach.tsv (func, name, level), out/objects_alive.tsv (id, name, sprite, evidence, level), out/sprite_reach.tsv (id, name, reach, draw functions, reachable at strict, example owner)."""
import collections
import json
import re


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


objs = list(tsv('out/objects.tsv'))[1:]
obj_index = {o[1]: i for i, o in enumerate(objs)}
names = dict(tsv('out/sprites/funcmap.tsv'))
slot_name = dict(tsv('out/sprites/slots.tsv'))

# --- call graph, draw sites ---
script_by_name = {n[len('gml_Script_'):]: fn for fn, n in names.items() if n.startswith('gml_Script_')}
DEBUG_SLOTS = set(json.load(open('out/sprite_config.json'))['debug_slots'])  # `debug`, `god_debug` slot VAs (woh.py resolves them by name): assumed false; Flow.java was run with them


def live(r):
    """flow.tsv rows carry a dead flag (site in a block that is unreachable when the debug variables are false)."""
    k = r[0]
    return not ((k == 'C' and r[4] == '1') or (k in ('R', 'G') and r[3] == '1') or (k in ('D', 'W') and r[8] == '1'))


flow_rows = [r for r in tsv('out/sprites/flow.tsv')]
dead_sites = {r[2] for r in flow_rows if r[0] == 'K'}
debug_writers = {r[1] for r in flow_rows if r[0] == 'W' and r[3] in DEBUG_SLOTS and live(r)}  # e.g. the main-menu shortcut handler that sets the flag
calls = collections.defaultdict(set)
draws_in = collections.defaultdict(set)  # sprite id -> functions with a draw call using it as a constant
for r in flow_rows:
    if not live(r):
        continue
    if r[0] == 'C':
        calls[r[1]].add(r[2])
    elif r[0] == 'D':
        for c in r[4].split(','):
            if c:
                draws_in[int(c)].add(r[1])
    elif r[0] == 'R':
        target = script_by_name.get(slot_name.get(r[2], ''))
        if target and target != r[1]:
            calls[r[1]].add(target)

# --- object creation sites (functions) ---
placed = {i for i, o in enumerate(objs) if int(o[4])}
create_funcs = collections.defaultdict(set)
for r in tsv('out/sprites/scriptcalls.tsv'):
    a = r[4].split(',')
    if len(a) == 3 and a[2].startswith('c:') and r[0] not in dead_sites:
        create_funcs[int(float(a[2][2:]))].add(r[1])
for r in tsv('out/sprites/bcalls.tsv'):
    if r[0] in dead_sites:
        continue
    # sprite draws that go through the builtin-by-id helper instead of a native (only draw_sprite_tiled / _ext are used this way): arg 0 is the sprite
    if slot_name.get(r[2], '').startswith('draw_sprite') and r[4].startswith('c:'):
        draws_in[int(float(r[4].split(',')[0][2:]))].add(r[1])
    if slot_name.get(r[2]) == 'instance_create_depth':
        a = r[4].split(',')
        if len(a) == 4 and a[3].startswith('c:'):
            create_funcs[int(float(a[3][2:]))].add(r[1])
id_funcs = collections.defaultdict(set)  # object index -> functions holding its id as a constant (call argument or stored value)
for r in tsv('out/sprites/scriptcalls.tsv'):
    for a in r[4].split(','):
        if a.startswith('c:') and r[0] not in dead_sites:
            id_funcs[int(float(a[2:]))].add(r[1])
for r in tsv('out/sprites/bcalls.tsv'):
    for a in r[4].split(','):
        if a.startswith('c:') and r[0] not in dead_sites:
            id_funcs[int(float(a[2:]))].add(r[1])
for r in flow_rows:
    if r[0] == 'W' and live(r):
        for c in r[4].split(','):
            if c:
                id_funcs[int(c)].add(r[1])

# --- roots ---
by_object = collections.defaultdict(list)  # object index -> event functions
roots_always = []
for fn, name in names.items():
    m = re.match(r'gml_Object_(.+)_(?:Create|Destroy|Alarm|Step|Collision|Mouse|Keyboard|KeyPress|KeyRelease|Other|Draw|Gesture|CleanUp|PreCreate|Async\w*)_\d+$', name)
    if m and m.group(1) in obj_index:
        if fn not in debug_writers:  # the shortcut that turns debug mode on does not run during a normal playthrough
            by_object[obj_index[m.group(1)]].append(fn)
    elif name.startswith(('gml_Room_', 'gml_RoomCC_', 'gml_GlobalScript_')):
        roots_always.append(fn)


def ancestors(i):
    out, seen = [], set()
    while 0 <= i < len(objs) and i not in seen:
        out.append(i)
        seen.add(i)
        i = int(objs[i][3])
    return out


def reach(alive):
    roots = set(roots_always)
    for i in alive:
        for a in ancestors(i):
            roots.update(by_object[a])
    seen, stack = set(roots), list(roots)
    while stack:
        for c in calls.get(stack.pop(), ()):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


alive = set(placed)
while True:
    funcs = reach(alive)
    grown = alive | {i for i, cf in create_funcs.items() if cf & funcs}
    if grown == alive:
        break
    alive = grown
strict_alive = alive

# Objects of one family (`evt_012_x`, `nenm_005_y`, ...) have consecutive ids (step 1 for most pairs), so the game can build an id as base + n; a member
# nobody names is then still creatable when a neighbour is live. Runs = same prefix, id gap <= 3.
family_of = {}
by_prefix = collections.defaultdict(list)
for i, o in enumerate(objs):
    m = re.match(r'([a-z]+)_\d+_', o[1])
    if m:
        by_prefix[m.group(1)].append(i)
for prefix, members in by_prefix.items():
    run = 0
    for k, i in enumerate(members):
        if k and i - members[k - 1] > 3:
            run += 1
        family_of[i] = (prefix, run)
family_members = collections.defaultdict(set)
for i, key in family_of.items():
    family_members[key].add(i)


def with_family(group):
    keys = {family_of[i] for i in group if i in family_of}
    out = set(group)
    for key in keys:
        out |= family_members[key]
    return out


moderate_alive = with_family(alive)
while True:
    funcs_m = reach(moderate_alive)
    grown = with_family(moderate_alive | {i for i, fs in id_funcs.items() if i < len(objs) and fs & funcs_m})
    if grown == moderate_alive:
        break
    moderate_alive = grown
sets = [('strict', funcs), ('moderate', funcs_m), ('loose', reach(set(range(len(objs)))))]
for label, s in sets:
    print(label, len(s), 'functions reachable')
print('objects alive: strict', len(strict_alive), '| moderate', len(moderate_alive), '| creation sites known for', len(create_funcs))

with open('out/objects_alive.tsv', 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\tsprite\tevidence\tlevel\n')
    for i, o in enumerate(objs):
        if i in placed:
            ev = 'room'
        elif i in strict_alive:
            ev = 'const'
        elif i in create_funcs and create_funcs[i] & funcs_m:
            ev = 'const-weak'  # created with a literal id, but only by code that runs if weakly-evidenced objects exist
        elif i in create_funcs:
            ev = 'const-unreachable'
        elif i in moderate_alive and i in id_funcs:
            ev = 'idconst'
        elif i in moderate_alive:
            ev = 'family'
        elif i in id_funcs:
            ev = 'idconst-unreachable'
        else:
            ev = 'none'
        level = 'strict' if i in strict_alive else 'moderate' if i in moderate_alive else 'loose'
        f.write('%d\t%s\t%s\t%s\t%s\n' % (i, o[1], o[2], ev, level))

with open('out/func_reach.tsv', 'w', encoding='utf-8', newline='\n') as f:
    f.write('func' + chr(9) + 'name' + chr(9) + 'level' + chr(10))
    every = set(names) | set(calls) | {c for cs in calls.values() for c in cs}
    for fn in sorted(every):
        level = next((label for label, s in sets if fn in s), 'none')
        f.write(fn + chr(9) + names.get(fn, '') + chr(9) + level + chr(10))

rows = list(tsv('out/sprite_usage.tsv'))[1:]
tally = collections.Counter()
with open('out/sprite_reach.tsv', 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\treach\tdraw_functions\treachable_at_strict\texample_owner\n')
    for r in rows:
        sid = int(r[0])
        fs = draws_in.get(sid, set())
        if not fs:
            continue
        level = next((label for label, s in sets if fs & s), 'none')
        tally[level] += 1
        f.write('%d\t%s\t%s\t%d\t%d\t%s\n' % (sid, r[1], level, len(fs), len(fs & sets[0][1]), names.get(sorted(fs)[0], sorted(fs)[0])))
print(dict(tally))
