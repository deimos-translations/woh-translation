"""Глобальная неподвижная точка по выходу Flow.java: `python -I flow_solve.py <flow.tsv> <slots.tsv> <sprite_usage.tsv> <out.tsv>`
value(var) = константы, записанные в var  U  value(v) для каждой переменной v, скопированной в неё.
Спрайт помечается `flow-drawn`, когда операнд id нативной функции спрайта — константа (по любому пути) или читает переменную, набор значений которой её содержит.
Колонки out: id, name, tier, via (const | var:<name> ...), indirect (1, если достигнут только через переменную)."""
import collections
import sys

flow, slots_p, usage_p, out_p = sys.argv[1:5]
with open(slots_p) as file:
    nm = dict(l.rstrip('\n').split('\t') for l in file)
def label(v):
    return nm.get(v, v)

consts = collections.defaultdict(set)
edges = collections.defaultdict(set)   # dest -> source variables
draws = []
with open(flow) as file:
    for line in file:
        f = line.rstrip('\n').split('\t')
        if f[0] in ('X', 'C', 'R', 'G'):  # unmodelled accessor log / call graph / slot reads
            continue
        if f[0] in ('K', 'N', 'E') or (f[0] in ('D', 'W') and f[8] == '1'):  # dead-block markers / rows inside blocks that are dead with debug mode off
            continue
        kind, dest, cs, vs, unk = f[0], f[3], f[4], f[5], f[7]
        cl = {int(c) for c in cs.split(',') if c}
        vl = {v for v in vs.split(',') if v}
        if kind == 'W':
            consts[dest] |= cl
            edges[dest] |= vl - {dest}
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

with open(usage_p, encoding='utf-8') as file:
    rows = [l.rstrip('\n').split('\t') for l in file][1:]
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
            out.write(f"{i}\t{r[1]}\t{r[2]}\t{','.join(sorted(via[i]))}\n")
print('draw sites', len(draws), '| unresolved', sum(1 for d in draws if d[3]), '| sprites reached', len(via))
