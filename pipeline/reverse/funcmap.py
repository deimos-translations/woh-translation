"""function VA -> GML name: `python -I funcmap.py <exe> <out.tsv>`
The runtime reads a table in .data of triples (name pointer, function, data pointer), 24 bytes each; the name is a string `gml_Object_<obj>_<Event>_<n>` or
`gml_Script_<name>` in .rdata. We find every qword that points at such a string and take the qword right after it as the function."""

import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common

BASE = 0x140000000
NAME = re.compile(rb"gml_(?:Object|Script|GlobalScript|RoomCC|Room)_[A-Za-z0-9_]+\0")


def main(exe, out):
    data = pathlib.Path(exe).read_bytes()
    sections = common.pe_sections(data)

    def offset_of(vaddr):
        rel = vaddr - BASE
        for vsize, rva, rsize, raw in sections.values():
            if rva <= rel < rva + min(vsize, rsize):
                return raw + rel - rva
        return None

    _, _, data_rsize, data_raw = sections[".data"]
    text_vsize, text_rva, _, _ = sections[".text"]
    image_end = BASE + max(rva + vsize for vsize, rva, _, _ in sections.values())
    functions = {}
    names = 0
    for position in range(data_raw, data_raw + data_rsize - 16, 8):
        pointer = struct.unpack_from("<Q", data, position)[0]
        if not BASE < pointer < image_end:
            continue
        target = offset_of(pointer)
        if target is None:
            continue
        # read the string at the pointer: pooled strings can share bytes, so a scan of the whole image misses some
        match = NAME.match(data, target)
        if match is None:
            continue
        names += 1
        function = struct.unpack_from("<Q", data, position + 8)[0]
        if BASE + text_rva <= function < BASE + text_rva + text_vsize:
            functions.setdefault(function, match.group(0)[:-1].decode())
    with pathlib.Path(out).open("w", encoding="utf-8", newline="\n") as file:
        file.writelines(
            f"{function:x}\t{name}\n" for function, name in sorted(functions.items())
        )
    print(len(functions), "functions named,", names, "name pointers")


if __name__ == "__main__":
    main(*sys.argv[1:3])
