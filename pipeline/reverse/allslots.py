"""Map of built-in function and variable slots: `python -I allslots.py <exe>` prints `<slot VA hex>\t<name>` to stdout.
A slot is `[name pointer][dword id, initially 0xffffffff]` in .data; the name lives in .rdata."""

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common

BASE = 0x140000000
data_bytes = pathlib.Path(sys.argv[1]).read_bytes()
sections = common.pe_sections(data_bytes)


def offset_of(va):
    rva = va - BASE
    for vsize, section_rva, rsize, raw in sections.values():
        if section_rva <= rva < section_rva + max(vsize, rsize):
            return raw + rva - section_rva
    return None


data_vsize, data_rva, data_rsize, data_raw = sections[".data"]
rdata_vsize, rdata_rva, _, _ = sections[".rdata"]
low, high = BASE + data_rva, BASE + data_rva + data_vsize
rdata_low, rdata_high = BASE + rdata_rva, BASE + rdata_rva + rdata_vsize
slots = {}
for index in range(data_rsize // 8):
    pointer = struct.unpack_from("<Q", data_bytes, data_raw + index * 8)[0]
    if rdata_low <= pointer < rdata_high:
        start = offset_of(pointer)
        name = data_bytes[start : start + 64].split(b"\0")[0]
        # the layout check lets 1-2 character names (x, y, id) in without noise
        if re.fullmatch(rb"[a-z][a-z0-9_]{0,50}", name) and (
            len(name) >= 3
            or struct.unpack_from("<I", data_bytes, data_raw + index * 8 + 8)[0]
            == 0xFFFFFFFF
        ):
            slots[low + index * 8 + 8] = name.decode()
for slot, name in sorted(slots.items()):
    print(f"{slot:x}\t{name}")
