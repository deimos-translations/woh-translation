import struct, sys, re
d = open(sys.argv[1],'rb').read(); B=0x140000000
pe = struct.unpack_from('<I', d, 0x3c)[0]; n = struct.unpack_from('<H', d, pe+6)[0]; so = struct.unpack_from('<H', d, pe+20)[0]
secs = [(d[pe+24+so+i*40:pe+24+so+i*40+8].rstrip(b'\0').decode(),)+struct.unpack_from('<IIII', d, pe+24+so+i*40+8) for i in range(n)]
def off(va):
    r=va-B
    for nm,vs,sva,rs,rp in secs:
        if sva <= r < sva+max(vs,rs): return rp+r-sva
data=[s for s in secs if s[0]=='.data'][0]; rd=[s for s in secs if s[0]=='.rdata'][0]
lo,hi=B+data[2],B+data[2]+data[1]
rlo,rhi=B+rd[2],B+rd[2]+rd[1]
o0=data[4]; cnt=data[3]//8
out={}
for i in range(cnt):
    q=struct.unpack_from('<Q',d,o0+i*8)[0]
    if rlo<=q<rhi:
        s=d[off(q):off(q)+64].split(b'\0')[0]
        # a slot is `[name pointer][dword id, initially 0xffffffff]`; the layout check lets 1-2 character names (x, y, id) in without noise
        if re.fullmatch(rb'[a-z][a-z0-9_]{0,50}', s) and (len(s) >= 3 or struct.unpack_from('<I',d,o0+i*8+8)[0] == 0xffffffff):
            out[lo+i*8+8]=s.decode()
for k,v in sorted(out.items()): print('%x\t%s'%(k,v))
