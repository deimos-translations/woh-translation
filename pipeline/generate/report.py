"""Final classification of every sprite and frame: `report.py <data.win>`, run by woh.py from the build's cache directory.

  USED    drawn by code that surely runs: a constant-id draw in strictly reachable code, a draw through a variable found by flow analysis, or the default
          sprite of an object that surely exists and is drawn by the engine / draws sprite_index.
  WEAK    drawn only by code that runs if weakly-evidenced objects exist (`@moderate`: ids in tables / family neighbours; `@loose`: objects nothing
          visibly creates) or by the default sprite of such an object.
  MAYBE   indirect evidence only: a constant stored in a sprite variable with no draw read found, a constant whose consumer could not be resolved, the
          default sprite of an object whose Draw event draws other sprites (leans unused), ids that collide with numbers. The `note` says which way it leans.
  UNUSED  no use found: no reference, only arithmetic / coordinate uses, or the default sprite of an object nothing creates.
Frames: a sprite drawn only with constant sub-images has exact frames (frames never drawn are UNUSED, frames drawn only in weaker code are at most WEAK);
a sprite with a variable sub-image or another route (object default, sprite variable) keeps its class for every frame, basis `dynamic` (it is used, which
frame shows is decided at run time).
Outputs: out/sprite_report.tsv, out/sprite_frame_report.tsv, out/sprite_report.md."""
import collections
import re
import struct
import sys

SMALL_ID = 40  # ids below this collide with plain numbers
ORDER = ['USED', 'WEAK', 'MAYBE', 'UNUSED']


def tsv(path):
    return (l.rstrip('\n').split('\t') for l in open(path, encoding='utf-8'))


def rows(path):
    return list(tsv(path))[1:]


d = open(sys.argv[1], 'rb').read()
chunks = {}
pos = 8
while pos < len(d):
    chunks[d[pos:pos + 4].decode('latin1')] = pos + 8
    pos += 8 + struct.unpack_from('<I', d, pos + 4)[0]
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
            return ('USED' if strong else 'WEAK'), 'default sprite of an object %s; %s' % ('placed or created by reachable code' if strong else 'that exists only weakly (%s)' % evidence, how)
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
            summary = 'constant: frames %s drawn, %s never drawn' % (used_all, fr[9])
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
                    fcls, fnote = 'UNUSED', 'frame never drawn (the sprite is only drawn at frames %s)' % fr[6]
        frame_rows.append((sid, name, f, fcls, basis, verdict, fnote))

with open('out/sprite_report.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\tclass\tverdict\tframes\tframe_use\tnote\n')
    for r in sprite_rows:
        out.write('\t'.join(map(str, r)) + '\n')
with open('out/sprite_frame_report.tsv', 'w', encoding='utf-8', newline='\n') as out:
    out.write('id\tname\tframe\tclass\tbasis\tverdict\tnote\n')
    for r in frame_rows:
        out.write('\t'.join(map(str, r)) + '\n')

by_class = collections.defaultdict(list)
for r in sprite_rows:
    by_class[r[2]].append(r)
frame_tally = collections.Counter(r[3] for r in frame_rows)
dynamic_frames = collections.Counter(r[3] for r in frame_rows if r[4] == 'dynamic')
with open('out/sprite_report.md', 'w', encoding='utf-8', newline='\n') as md:
    md.write('# Sprite usage report\n\nGenerated by `woh.py report`. Debug mode is assumed off (`debug`, `god_debug` = false).\n\n')
    md.write('| class | sprites | frames |\n|---|---|---|\n')
    for cls in ORDER:
        md.write('| %s | %d | %d |\n' % (cls, len(by_class[cls]), frame_tally[cls]))
    md.write('| total | %d | %d |\n\n' % (len(sprite_rows), len(frame_rows)))
    md.write('Frames with basis `dynamic` (the sprite is used, the frame is chosen at run time): %s.\n\n' % ', '.join('%s %d' % (c, dynamic_frames[c]) for c in ORDER))
    for cls in ('UNUSED', 'MAYBE', 'WEAK'):
        md.write('## %s (%d sprites)\n\n' % (cls, len(by_class[cls])))
        groups = collections.defaultdict(list)
        for r in by_class[cls]:
            groups[r[6]].append(r[1] + (' (%d frames)' % r[4] if r[4] > 1 else ''))
        for note, names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            md.write('- **%s** (%d): %s\n' % (note, len(names), ', '.join(names)))
        md.write('\n')
    part = [r for r in sprite_rows if r[5].startswith('constant') and not r[5].endswith(' never drawn') and r[2] in ('USED', 'WEAK')]
    md.write('## Sprites drawn only at constant frames (frames never drawn are UNUSED)\n\n')
    for r in part:
        md.write('- %s [%s]: %s\n' % (r[1], r[2], r[5]))
print({c: (len(by_class[c]), frame_tally[c]) for c in ORDER})
