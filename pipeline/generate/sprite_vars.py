"""Константы, присвоенные спрайтовым переменным, по каждому спрайту.
использование: python -I sprite_vars.py <sprite_usage.tsv> <slots.tsv> <lval.tsv> <setsites.tsv> <elem.tsv> <out.tsv>
Источники: lval.tsv (LvalStores.java: записи на месте через геттер lvalue), setsites.tsv (SetSites.java: вспомогательные функции установки) и elem.tsv
(ElemStores.java: константы, сохранённые в RValue, который возвращает аксессор, например `quest_image[i] = n`; корневая переменная находится обратным проходом с приближением).
SPRITE_VARS — суждение по именам (чтения переменных в вычисляемых местах отрисовки плюс имена, содержащие "image/art/icon"); само по себе значение
неоднозначно ниже ~40, потому что малые целые совпадают со счётчиками, поэтому каждое совпадение остаётся подсказкой, а не доказательством.
"""
import sys, collections

SPRITE_VARS = {
    'sprite_index', 'cursor_sprite', 'event_image', 'extra_image', 'quest_progress_image', 'quest_image', 'god_image', 'banked_art',
    'my_background', 'my_sprite', 'challenge_portrait', 'otherworld_img', 'spell_image', 'menu_image', 'shop_art', 'lefty_art', 'art1', 'art2',
    'art3', 'my_art01', 'my_art02', 'location_icon', 'ttimage', 'imago', 'portrait', 'chibi', 'standing', 'text_art', 'image', 'custom_art',
    'item_background', 'spell_background',
}
MIN_ID = 12  # below this, constants are mostly plain numbers

slots = dict(l.rstrip('\n').split('\t') for l in open(sys.argv[2]))
rows = [l.rstrip('\n').split('\t') for l in open(sys.argv[1], encoding='utf-8')][1:]
info = {int(r[0]): r for r in rows}
hits = collections.defaultdict(lambda: collections.Counter())

def add(slot, val):
    if not val or '.' in val:
        return
    sid = int(val)
    var = slots.get(slot)
    if var in SPRITE_VARS and MIN_ID <= sid < len(info):
        hits[sid][var] += 1

for line in open(sys.argv[3]):
    site, slot, kind, val = line.rstrip('\n').split('\t')
    if kind == 'const':
        add(slot, val)
for line in open(sys.argv[4]):
    f = line.rstrip('\n').split('\t')
    for val in f[4].split(','):
        add(f[2], val)

for line in open(sys.argv[5]):
    sid, _site, root, _depth, _callee = line.rstrip('\n').split('\t')
    add(root, sid)

with open(sys.argv[6], 'w', encoding='utf-8') as out:
    out.write('id\tname\ttier\tvars\n')
    for sid in sorted(hits):
        out.write(f"{sid}\t{info[sid][1]}\t{info[sid][2]}\t{','.join(f'{v}x{n}' for v, n in sorted(hits[sid].items()))}\n")
