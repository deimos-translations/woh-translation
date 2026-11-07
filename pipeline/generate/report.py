"""Итоговая классификация каждого спрайта и кадра: `report.py <data.win>`, запускается woh.py из папки кэша сборки.

  USED    отрисовывается кодом, который наверняка выполняется: отрисовка с константным id в строго достижимом коде, отрисовка через переменную, найденную анализом потока, или
          спрайт по умолчанию объекта, который наверняка существует и рисуется движком / рисует sprite_index.
  WEAK    отрисовывается только кодом, который выполняется, если существуют слабо подтверждённые объекты (`@moderate`: id в таблицах / соседи семейства; `@loose`: объекты, которые ничто
          видимо не создаёт), или спрайтом по умолчанию такого объекта.
  MAYBE   только косвенные признаки: константа, сохранённая в спрайтовую переменную, для которой не найдено чтение при отрисовке; константа, потребитель которой не удалось определить; спрайт по умолчанию
          объекта, чьё событие Draw рисует другие спрайты (склоняется к неиспользуемому); id, совпадающие с числами. `note` говорит, в какую сторону он склоняется.
  UNUSED  использование не найдено: нет ссылок, только арифметические / координатные использования, или спрайт по умолчанию объекта, который ничто не создаёт.
Кадры: спрайт, отрисованный только с константными подизображениями, имеет точные кадры (кадры, которые никогда не рисовались, — UNUSED; кадры, рисованные только в более слабом коде, — не выше WEAK);
спрайт с переменным подизображением или другим путём (спрайт по умолчанию объекта, спрайтовая переменная) сохраняет свой класс для каждого кадра, основание `dynamic` (он используется, а какой кадр показан, решается во время выполнения).
Выходные файлы: out/sprite_report.tsv, out/sprite_frame_report.tsv, out/sprite_report.md."""
import collections
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
import common

SMALL_ID = 40  # ids below this collide with plain numbers
ORDER = ['USED', 'WEAK', 'MAYBE', 'UNUSED']


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


def rows(path):
    return list(tsv(path))[1:]


d = pathlib.Path(sys.argv[1]).read_bytes()
chunks = common.data_win_chunks(d)
n_sprites = struct.unpack_from('<I', d, chunks['SPRT'])[0]
frame_count = [struct.unpack_from('<I', d, struct.unpack_from('<I', d, chunks['SPRT'] + 4 + 4 * i)[0] + 84)[0] for i in range(n_sprites)]

B_RE = re.compile(r'^B-(room|const-weak|const-unreachable|const|idconst-unreachable|idconst|family)-(auto|self-own|self-inherit|other-own|other-inherit|hidden)$')


def classify(sid, verdict):
    base, _, level = verdict.partition('@')
    if base in ('A', 'A-builtin', 'A-flow') or base.endswith('+drawn'):
        if level:
            return 'WEAK', 'drawn only in code that runs if %s objects exist' % ('id-table / family' if level == 'moderate' else 'evidence-free')
        return 'USED', 'drawn in reachable code'
    m = B_RE.match(base)
    if m:
        evidence, mode = m.groups()
        if evidence.endswith('unreachable'):
            return 'UNUSED', 'default sprite of an object whose only creator is unreachable'
        strong = evidence in ('room', 'const')
        if mode in ('auto', 'self-own', 'self-inherit'):
            how = 'the engine draws it' if mode == 'auto' else 'its Draw event draws sprite_index'
            return ('USED' if strong else 'WEAK'), 'default sprite of an object {}; {}'.format('placed or created by reachable code' if strong else f'that exists only weakly ({evidence})', how)
        if mode == 'hidden':
            return 'MAYBE', 'default sprite of an invisible object; leans unused'
        return 'MAYBE', 'default sprite of an object whose Draw event draws other sprites; leans unused'
    if base == 'B-none':
        return 'UNUSED', 'default sprite of an object nothing creates'
    if base == 'B-none+var':
        return 'MAYBE', 'default sprite of an object nothing creates, but assigned to a sprite variable'
    if base == 'C-assigned':
        return 'MAYBE', 'stored in a sprite variable, no draw read found' + ('; leans unused (small id collides with numbers)' if sid < SMALL_ID else '')
    if base == 'C-assigned-weak':
        return 'MAYBE', 'only stored in image/text_art-like variables that also take counters; leans unused'
    if base == 'C-unresolved':
        return 'MAYBE', 'its id appears as a constant whose consumer could not be resolved'
    if base == 'C-coord':
        return 'UNUSED', 'its id appears only in arithmetic or as a coordinate'
    if base in ('C-noconst', 'D'):
        return 'UNUSED', 'no reference found'
    return 'MAYBE', 'unclassified verdict ' + verdict


final = {int(r[0]): r for r in rows('out/sprite_final.tsv')}
frames_table = {int(r[0]): r for r in rows('out/sprite_frames.tsv')}

sprite_rows, frame_rows = [], []
sprite_class = {}
for sid in sorted(final):
    name, verdict = final[sid][1], final[sid][2]
    cls, note = classify(sid, verdict)
    sprite_class[sid] = cls
    fr = frames_table.get(sid)
    n = frame_count[sid]
    summary = ''
    if fr:
        used_all = fr[6]
        if used_all == 'dynamic' or fr[7]:
            summary = 'dynamic'
        else:
            summary = f'constant: frames {used_all} drawn, {fr[9]} never drawn'
    sprite_rows.append((sid, name, cls, verdict, n, summary, note))
    for f in range(n):
        fcls, fnote, basis = cls, note, 'single' if n == 1 else 'n/a'
        if fr:
            basis = 'dynamic'
            if fr[6] != 'dynamic' and not fr[7]:
                basis = 'constant'
                drawn_all = {int(u) for u in fr[6].split(',') if u}
                drawn_strict = {int(u) for u in fr[5].split(',') if u and u not in ('dynamic', '-')}
                if f in drawn_strict:
                    pass
                elif f in drawn_all:
                    if fcls == 'USED':
                        fcls, fnote = 'WEAK', 'frame drawn only in code that is not strictly reachable'
                else:
                    fcls, fnote = 'UNUSED', f'frame never drawn (the sprite is only drawn at frames {fr[6]})'
        frame_rows.append((sid, name, f, fcls, basis, verdict, fnote))

with open('out/sprite_report.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\tclass\tverdict\tframes\tframe_use\tnote\n')
    out.writelines('\t'.join(map(str, r)) + '\n' for r in sprite_rows)
with open('out/sprite_frame_report.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\tframe\tclass\tbasis\tverdict\tnote\n')
    out.writelines('\t'.join(map(str, r)) + '\n' for r in frame_rows)

by_class = collections.defaultdict(list)
for r in sprite_rows:
    by_class[r[2]].append(r)
frame_tally = collections.Counter(r[3] for r in frame_rows)
dynamic_frames = collections.Counter(r[3] for r in frame_rows if r[4] == 'dynamic')
with open('out/sprite_report.md', 'w', encoding='utf-8', newline='\n') as md:
    md.write('# Sprite usage report\n\nGenerated by `woh.py report`. Debug mode is assumed off (`debug`, `god_debug` = false).\n\n')
    md.write('| class | sprites | frames |\n|---|---|---|\n')
    for cls in ORDER:
        md.write(f'| {cls} | {len(by_class[cls])} | {frame_tally[cls]} |\n')
    md.write(f'| total | {len(sprite_rows)} | {len(frame_rows)} |\n\n')
    dynamic_text = ', '.join(f'{c} {dynamic_frames[c]}' for c in ORDER)
    md.write(f'Frames with basis `dynamic` (the sprite is used, the frame is chosen at run time): {dynamic_text}.\n\n')
    for cls in ('UNUSED', 'MAYBE', 'WEAK'):
        md.write(f'## {cls} ({len(by_class[cls])} sprites)\n\n')
        groups = collections.defaultdict(list)
        for r in by_class[cls]:
            groups[r[6]].append(r[1] + (f' ({r[4]} frames)' if r[4] > 1 else ''))
        for note, names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            md.write(f"- **{note}** ({len(names)}): {', '.join(names)}\n")
        md.write('\n')
    part = [r for r in sprite_rows if r[5].startswith('constant') and not r[5].endswith(' never drawn') and r[2] in ('USED', 'WEAK')]
    md.write('## Sprites drawn only at constant frames (frames never drawn are UNUSED)\n\n')
    for r in part:
        md.write(f'- {r[1]} [{r[2]}]: {r[5]}\n')
print({c: (len(by_class[c]), frame_tally[c]) for c in ORDER})
