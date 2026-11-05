"""Which translation images are used? Run by woh.py from the build's cache directory, last.
Maps every img/translation/*.png and every translation/todo.txt line (`img/source/<sprite>_<frame>.png`) to the frame classes of
out/sprite_frame_report.tsv (USED / WEAK / MAYBE / UNUSED, see report.py) and writes out/translation_audit.tsv."""
import collections
import os
import pathlib
import re

R = 'out/'
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def rows(path):
    return [l.rstrip('\n').split('\t') for l in open(R + path, encoding='utf-8')][1:]


frames = {(r[1], int(r[2])): r for r in rows('sprite_frame_report.tsv')}
sprites = {r[1] for r in rows('sprite_report.tsv')}


def parse(stem):
    if stem in sprites:
        return stem, 0
    m = re.match(r'^(.*)_(\d+)$', stem)
    return (m.group(1), int(m.group(2))) if m and m.group(1) in sprites else (None, None)


entries = [('translation', f[:-4]) for f in sorted(os.listdir(ROOT / 'img' / 'translation')) if f.endswith('.png')]
if (ROOT / 'translation' / 'todo.txt').exists():
    for line in open(ROOT / 'translation' / 'todo.txt', encoding='utf-8'):
        line = line.strip()
        if line:
            entries.append(('todo', os.path.basename(line)[:-4] if line.endswith('.png') else line))

tally = collections.Counter()
with open(R + 'translation_audit.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('source\tfile\tsprite\tframe\tclass\tbasis\tverdict\tnote\n')
    for source, stem in entries:
        sprite, frame = parse(stem)
        row = frames.get((sprite, frame))
        if row is None:
            out.write('%s\t%s\t?\t?\tUNPARSED\t\t\t\n' % (source, stem))
            tally[(source, 'UNPARSED')] += 1
            continue
        out.write('%s\t%s\t%s\t%d\t%s\t%s\t%s\t%s\n' % (source, stem, sprite, frame, row[3], row[4], row[5], row[6]))
        tally[(source, row[3])] += 1
print(', '.join('%s %s %d' % (s, c, n) for (s, c), n in sorted(tally.items())))
