"""Спрайты C, чьи константы-идентификаторы попадают только в координатные переменные: запускается woh.py из папки кэша сборки.
Малый id, например 207, совпадает с позицией y. Переменная является координатной, когда вызов отрисовки спрайта принимает её как аргумент x (XMM3) или y ([rsp+0x20])
(строки `D` flow.tsv, поля x3 / s20) -- `x`, `y`, `bya`, `bxa`, `tyy`, `char_x`, ... Если каждое живое сохранение константы (строки Flow `W` и
ElemStores `elem.tsv`) идёт в такие переменные, у спрайта нет использования как значения спрайта: out/sprite_coordonly.tsv (id, name, tier, stores, variables).
sprite_final.py читает его и превращает C-unresolved / C-assigned-weak / C-assigned в C-coord для этих спрайтов."""
import collections


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


slot_name = dict(tsv('out/sprites/slots.tsv'))
coord_slots = set()
stores = collections.defaultdict(list)  # sprite id -> destination slots
for r in tsv('out/sprites/flow.tsv'):
    if r[0] == 'D' and r[8] == '0':
        for field in (r[10], r[11]):
            if field.startswith('v:'):
                coord_slots.update(field[2:].rstrip('+').split(','))
    elif r[0] == 'W' and r[8] == '0':
        for c in r[4].split(','):
            if c:
                stores[int(c)].append(r[3])
for r in tsv('out/sprites/elem.tsv'):
    stores[int(r[0])].append(r[2])

tiers = {int(r[0]): r for r in list(tsv('out/sprite_usage.tsv'))[1:]}
count = 0
with open('out/sprite_coordonly.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\ttier\tstores\tvariables\n')
    for sid, r in sorted(tiers.items()):
        if r[2] != 'C' or sid not in stores:
            continue
        dests = stores[sid]
        if all(d in coord_slots for d in dests):
            count += 1
            out.write('%d\t%s\t%s\t%d\t%s\n' % (sid, r[1], r[2], len(dests), ','.join(sorted({slot_name.get(d, d) for d in dests}))))
print(count, 'C sprites whose constants only go into coordinate variables')
