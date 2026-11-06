"""Какие кадры (подизображения) каждого спрайта рисует игра? `frames.py <data.win>`, запускается woh.py из папки кэша сборки.

Нативные функции отрисовки принимают (instance, sprite, sub-image, x, y, ...): sub-image — аргумент XMM2 (строки `D` Flow.java, поле x2); путь через
встроенную функцию draw_sprite_tiled(_ext) принимает его как аргумент 1. Константное sub-image называет один кадр; переменная (image_index, счётчик) или неизвестное значение означает,
что спрайт анимирован или выбирается во время выполнения, то есть любой кадр может появиться; -1 означает "image_index экземпляра", тоже динамически.
Использованные кадры спрайта являются доказательством, только если КАЖДЫЙ путь к экрану — отрисовка с константным кадром, поэтому спрайт помечается `dynamic`, как только он также
  - является спрайтом по умолчанию объекта, который может существовать (движок / draw_self / sprite_index анимируют его через image_speed),
  - присвоен спрайтовой переменной (sprite_vars.py) или достигается через переменную при отрисовке (flow_solve.py).
Использованные кадры перечисляются по уровню достижимости (func_reach.tsv): `strict` учитывает только отрисовки в коде, который наверняка выполняется.
Вывод: out/sprite_frames.tsv (id, name, frames, fps_or_speed, level, used_strict, used_all, dynamic_reasons, unused_strict, unused_all)."""
import collections
import math
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
import common


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


d = pathlib.Path(sys.argv[1]).read_bytes()
chunks = common.data_win_chunks(d)
sprt = chunks['SPRT']
n_sprites = struct.unpack_from('<I', d, sprt)[0]
ptrs = struct.unpack_from(f'<{n_sprites}I', d, sprt + 4)
frames = [struct.unpack_from('<I', d, q + 84)[0] for q in ptrs]  # word 21: frame count, then the TPAG pointers
speed = [struct.unpack_from('<f', d, q + 68)[0] for q in ptrs]

names = {int(r[0]): r[1] for r in list(tsv('out/sprite_usage.tsv'))[1:]}
func_level = {r[0]: r[2] for r in list(tsv('out/func_reach.tsv'))[1:]}
rank = {'strict': 0, 'moderate': 1, 'loose': 2, 'none': 3}
slot_name = dict(tsv('out/sprites/slots.tsv'))

# --- constant-id draw sites: (sprite, function, subimage) ---
sites = []  # (sprite id, function, frame number or None for dynamic)


def frame_of(text):
    if text.startswith('k:'):
        value = float(text[2:])
        return None if value < 0 else math.floor(value)
    return None  # v:..., u, anything else


for r in tsv('out/sprites/flow.tsv'):
    if r[0] == 'D' and r[8] == '0' and len(r) > 9:
        for c in r[4].split(','):
            if c and int(c) < n_sprites:
                sites.append((int(c), r[1], frame_of(r[9])))
for r in tsv('out/sprites/bcalls.tsv'):
    if slot_name.get(r[2], '').startswith('draw_sprite_tiled'):
        a = r[4].split(',')
        if a and a[0].startswith('c:') and int(float(a[0][2:])) < n_sprites:
            sites.append((int(float(a[0][2:])), r[1], frame_of('k:' + a[1][2:]) if len(a) > 1 and a[1].startswith('c:') else None))

# --- other routes that make the frame dynamic ---
reasons = collections.defaultdict(set)
sprite_of_name = {v: k for k, v in names.items()}
for r in list(tsv('out/objects_alive.tsv'))[1:]:
    if r[2] in sprite_of_name and r[3] != 'none' and not r[3].endswith('unreachable'):
        reasons[sprite_of_name[r[2]]].add('object-default')
for r in list(tsv('out/sprite_varassign.tsv'))[1:]:
    reasons[int(r[0])].add('variable')
for r in list(tsv('out/sprite_flow.tsv'))[1:]:
    if 'var:' in r[3]:
        reasons[int(r[0])].add('variable-draw')

used = {lv: collections.defaultdict(set) for lv in ('strict', 'all')}
dynamic = {lv: collections.defaultdict(bool) for lv in ('strict', 'all')}
site_count = collections.Counter()
best_level = {}
for sid, fn, fr in sites:
    lv = func_level.get(fn, 'none')
    site_count[sid] += 1
    if sid not in best_level or rank[lv] < rank[best_level[sid]]:
        best_level[sid] = lv
    for scope in ('all',) + (('strict',) if lv == 'strict' else ()):
        if fr is None:
            dynamic[scope][sid] = True
        else:
            used[scope][sid].add(fr % max(frames[sid], 1))


def describe(scope, sid):
    if dynamic[scope][sid] or reasons.get(sid):
        return 'dynamic', frames[sid]
    got = used[scope].get(sid, set())
    return ','.join(map(str, sorted(got))), frames[sid] - len(got)


summary = collections.Counter()
with open('out/sprite_frames.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\tframes\tspeed\tlevel\tused_strict\tused_all\tdynamic_reasons\tunused_strict\tunused_all\n')
    for sid in sorted(site_count):
        why = sorted(reasons.get(sid, set()) | ({'variable-frame'} if dynamic['all'][sid] else set()))
        us, uns = describe('strict', sid) if sid in used['strict'] or dynamic['strict'][sid] else ('-', frames[sid])
        ua, una = describe('all', sid)
        if us == 'dynamic' or ua == 'dynamic':
            summary['dynamic sprites'] += 1
        elif frames[sid] > 1:
            summary['constant-frame multi-frame sprites'] += 1
            summary['unused frames (any level)'] += una
        out.write(f"{sid}\t{names[sid]}\t{frames[sid]}\t{speed[sid]:.3g}\t{best_level[sid]}\t{us}\t{ua}\t{','.join(why)}\t{uns}\t{una}\n")
print('constant-id draws of', len(site_count), 'sprites;', dict(summary))
