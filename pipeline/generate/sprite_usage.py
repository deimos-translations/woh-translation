"""Статический отчёт об использовании спрайтов: `python -I sprite_usage.py <data.win> <sites.tsv> <consts.tsv> <out.tsv> <sink> ...` (выходные данные SpriteRefs.java).
Id спрайта — это индекс SPRT. Уровни, от сильнейшего:
  A  нативная функция draw_sprite* вызывается с этим id как литералом (`MOV EDX,imm`) — отрисовывается, если вызов не недостижим
  B  спрайт по умолчанию одного или нескольких объектов в data.win (OBJT) — отрисовывается через draw_self / при отсутствии события Draw
  C  id встречается только как double-константа в коде игры — кандидат (может быть координатой, равной id)
  D  ссылок не найдено — не отрисовывается, если только id не вычисляется или имя не ищется во время выполнения
Стоки — нативные функции, в которых id спрайта находится в RDX."""
import collections
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
import common

data_win, sites, consts, out = sys.argv[1:5]
sinks = set(sys.argv[5:])
d = pathlib.Path(data_win).read_bytes()
chunks = common.data_win_chunks(d)

def cstr(p):
    return d[p:d.index(b'\0', p)].decode('utf-8', 'replace')

def table(chunk):
    o = chunks[chunk]
    count = struct.unpack_from('<I', d, o)[0]
    return struct.unpack_from(f'<{count}I', d, o + 4)

sprites = [cstr(struct.unpack_from('<I', d, p)[0]) for p in table('SPRT')]
users = collections.defaultdict(list)
for p in table('OBJT'):
    spr = struct.unpack_from('<i', d, p + 4)[0]
    if spr >= 0: users[spr].append(cstr(struct.unpack_from('<I', d, p)[0]))

drawn = collections.defaultdict(list)  # sprite -> [function VA]
dynamic = 0
with open(sites) as file:
    for line in file:
        sink, call, func, reg, val = line.rstrip('\n').split('\t')
        if reg != 'RDX' or sink not in sinks: continue
        if val.isdigit(): drawn[int(val)].append(func)
        else: dynamic += 1
dconst = {}
with open(consts) as file:
    for line in file:
        row = line.rstrip('\n').split('\t')
        dconst[int(row[0])] = int(row[1])

tally = collections.Counter()
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    f.write('id\tname\ttier\tdraw_sites\tfunctions\tobjects\tdouble_consts\n')
    for i, name in enumerate(sprites):
        tier = 'A' if i in drawn else 'B' if i in users else 'C' if dconst[i] else 'D'
        tally[tier] += 1
        funcs = sorted(set(drawn[i]))
        f.write(f"{i}\t{name}\t{tier}\t{len(drawn[i])}\t{' '.join(funcs[:4])}\t{' '.join(users[i][:4])}\t{dconst[i]}\n")
print(dict(sorted(tally.items())), 'sprites', len(sprites), '| draw sites with a computed sprite id:', dynamic)
