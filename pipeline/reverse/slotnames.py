"""Заменяет слоты id встроенных функций в декомпилированных .c файлах на имена: `python -I slotnames.py <exe> <file.c>...` (записывает <file>.named.c).
Вызов встроенной функции: FUN_1420df500(self,other,&ret,argc,CONCAT44(x,DAT_slot),args); указатель на имя слота находится на 8 байт ДО него."""
import re, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slotstrings
LIT = slotstrings.load(sys.argv[1])
d = open(sys.argv[1], 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe + 6)[0]; so = struct.unpack_from('<H', d, pe + 20)[0]
secs = [struct.unpack_from('<IIII', d, pe + 24 + so + i * 40 + 8) for i in range(n)]
def rd(va, ln):
    r = va - 0x140000000
    for vs, sva, rs, rp in secs:
        if sva <= r < sva + max(vs, rs): return d[rp + r - sva: rp + r - sva + ln]
def name(slot):
    b = rd(slot - 8, 8)
    if not b: return None
    q = struct.unpack('<Q', b)[0]
    s = rd(q, 64) if 0x140000000 <= q < 0x150000000 else None
    if not s: return None
    s = s.split(b'\0')[0]
    return s.decode('latin1') if re.fullmatch(rb'[A-Za-z_][A-Za-z0-9_]{2,60}', s) else None
for f in sys.argv[2:]:
    t = open(f).read()
    def sub(m):
        va = int(m.group(1), 16)
        if va in LIT: return f'{m.group(0)}/*{LIT[va]!r}*/'
        nm = name(va)
        return f'{m.group(0)}/*{nm}*/' if nm else m.group(0)
    open(f[:-2] + '.named.c', 'w').write(re.sub(r'DAT_(1[0-9a-f]{8})(?=[);,])', sub, t))
