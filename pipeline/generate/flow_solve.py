"""Global fixpoint over Flow.java output: `python -I flow_solve.py <flow.tsv> <slots.tsv> <sprite_usage.tsv> <out.tsv>`
value(var) = constants written to var  U  value(v) for every variable v copied into it (arith kept as a flag, not followed numerically).
A sprite is `flow-drawn` when a sprite native's id operand is a constant (any route) or reads a variable whose value set contains it.
out cols: id, name, tier, via (const | var:<name> ...), indirect (1 if reached only through a variable)."""
import collections, sys

flow, slots_p, usage_p, out_p = sys.argv[1:5]
nm = dict(l.rstrip('\n').split('\t') for l in open(slots_p))
def label(v):
    return nm.get(v, v)

consts = collections.defaultdict(set)
edges = collections.defaultdict(set)   # dest -> source variables
arith = set()
draws = []
for line in open(flow):
    f = line.rstrip('\n').split('\t')
    if f[0] in ('X', 'C', 'R', 'G'):  # unmodelled accessor log / call graph / slot reads
        continue
    if f[0] in ('K', 'N', 'E') or (f[0] in ('D', 'W') and f[8] == '1'):  # dead-block markers / rows inside blocks that are dead with debug mode off
        continue
    kind, dest, cs, vs, ar, unk = f[0], f[3], f[4], f[5], f[6], f[7]
    cl = {int(c) for c in cs.split(',') if c}
    vl = {v for v in vs.split(',') if v}
    if kind == 'W':
        consts[dest] |= cl
        edges[dest] |= vl - {dest}
        if ar == '1':
            arith.add(dest)
    else:
        draws.append((f[2], cl, vl, unk == '1'))

value = {v: set(c) for v, c in consts.items()}
changed = True
while changed:
    changed = False
    for dest, srcs in edges.items():
        cur = value.setdefault(dest, set())
        for s in srcs:
            add = value.get(s, set()) - cur
            if add:
                cur |= add
                changed = True

rows = [l.rstrip('\n').split('\t') for l in open(usage_p, encoding='utf-8')][1:]
count = len(rows)
via = collections.defaultdict(set)
for site, cl, vl, unk in draws:
    for c in cl:
        if c < count:
            via[c].add('const')
    for v in vl:
        for c in value.get(v, ()):
            if c < count:
                via[c].add('var:' + label(v))
with open(out_p, 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\ttier\tvia\n')
    for r in rows:
        i = int(r[0])
        if i in via:
            out.write('%d\t%s\t%s\t%s\n' % (i, r[1], r[2], ','.join(sorted(via[i]))))
print('draw sites', len(draws), '| unresolved', sum(1 for d in draws if d[3]), '| sprites reached', len(via))
