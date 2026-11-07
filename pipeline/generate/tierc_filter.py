"""Уточнение Tier C: классифицирует каждый спрайт C по тому, что получает его двойные константы-идентификаторы.
использование: python -I scripts/tierc_filter.py <sprite_usage.tsv> <consumers.tsv> <slots.tsv> <out.tsv>
verdict: assigned  = вспомогательная функция установки переменной получает его (перечислены имена слотов)
         unresolved = у некоторой константы нет найденного потребителя (сохранена в RValue/элемент массива/статическую таблицу)
         coord     = каждый найденный потребитель — арифметика/сравнение (`+= -= *=`, compare, free)
"""
import json, sys, collections

SYMBOLS = json.load(open('out/symbols.json'))  # run from the build's cache directory
ARITH = {SYMBOLS['compare'], *SYMBOLS['arith'], *SYMBOLS['free'], *SYMBOLS['tierc_arith']}
SETTERS = {*SYMBOLS['setters'], SYMBOLS['rvalue_copy']}
NUMERIC_VARS = {'alarm', 'room_speed', 'image_index'}  # setting these is a number, not a sprite
INT_CONV = SYMBOLS['to_int']  # RValue -> int: neutral (array index, argument conversion)

slots = dict(l.rstrip('\n').split('\t') for l in open(sys.argv[3]))
rows = [l.rstrip('\n').split('\t') for l in open(sys.argv[1], encoding='utf-8')][1:]
tier = {int(r[0]): r[2] for r in rows}
name = {int(r[0]): r[1] for r in rows}
kinds = collections.defaultdict(collections.Counter)
setvars = collections.defaultdict(set)
for line in open(sys.argv[2]):
    sid, _, callee, _, slot = line.rstrip('\n').split('\t')
    sid = int(sid)
    if tier.get(sid) != 'C':
        continue
    if callee in ARITH:
        kind = 'arith'
    elif callee in SETTERS:
        var = slots.get(slot, slot)
        kind = 'arith' if var in NUMERIC_VARS else 'set'
        if kind == 'set':
            setvars[sid].add(var)
    elif callee == INT_CONV:
        kind = 'int'
    elif callee in ('-', 'nostore'):
        kind = 'none'
    else:
        kind = 'other'
    kinds[sid][kind] += 1

with open(sys.argv[4], 'w', encoding='utf-8') as out:
    out.write('id\tname\tverdict\tarith\tset\tint\tother\tnone\tsetvars\n')
    for sid in sorted(kinds):
        k = kinds[sid]
        verdict = 'assigned' if k['set'] else 'unresolved' if k['none'] or k['other'] else 'coord'
        out.write('\t'.join(map(str, (sid, name[sid], verdict, k['arith'], k['set'], k['int'], k['other'], k['none'],
                                      ','.join(sorted(setvars[sid]))))) + '\n')
