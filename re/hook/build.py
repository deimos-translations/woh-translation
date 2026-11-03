"""Assemble re/hook/hook.s into re/hook/hook.bin + hook.json (needs clang on PATH; the outputs are committed).

Usage: python -I re/hook/build.py

hook.bin is the raw `.text` of the object. The only relocation is the REL32 of `lea r9,[rip+g_table]`; patch.py resolves it
once it knows where the table lives. hook.json: { "size": N, "relocations": [{"offset": o, "symbol": "g_table"}] }.
"""
import json
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent


def read_coff_text(path):
    data = path.read_bytes()
    _machine, nsec, _stamp, symtab, nsyms, _opt, _chars = struct.unpack_from("<HHIIIHH", data, 0)
    strtab = symtab + 18 * nsyms

    def symbol_name(index):
        entry = symtab + 18 * index
        if data[entry:entry + 4] == b"\0\0\0\0":
            offset = struct.unpack_from("<I", data, entry + 4)[0]
            return data[strtab + offset:data.index(b"\0", strtab + offset)].decode()
        return data[entry:entry + 8].rstrip(b"\0").decode()

    for i in range(nsec):
        header = 20 + 40 * i
        name, _vs, _va, raw_size, raw_ptr, reloc_ptr, _line, nrel = struct.unpack_from("<8sIIIIIIH", data, header)
        if name.rstrip(b"\0") != b".text":
            continue
        relocations = []
        for r in range(nrel):
            offset, symbol, kind = struct.unpack_from("<IIH", data, reloc_ptr + 10 * r)
            relocations.append({"offset": offset, "symbol": symbol_name(symbol), "type": kind})
        return data[raw_ptr:raw_ptr + raw_size], relocations
    raise SystemExit("no .text section")


def assemble(source, out):
    subprocess.run(["clang", "--target=x86_64-pc-windows-msvc", "-c", str(source), "-o", str(out)], check=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        obj = pathlib.Path(tmp) / "hook.obj"
        assemble(HERE / "hook.s", obj)
        text, relocations = read_coff_text(obj)
    assert all(r["type"] == 4 for r in relocations), "expected only IMAGE_REL_AMD64_REL32"  # 4 = REL32
    (HERE / "hook.bin").write_bytes(text)
    (HERE / "hook.json").write_text(json.dumps(
        {"size": len(text), "relocations": [{"offset": r["offset"], "symbol": r["symbol"]} for r in relocations]}, indent=2) + "\n")
    print(f"hook.bin {len(text)} bytes, relocations {[(r['offset'], r['symbol']) for r in relocations]}")


if __name__ == "__main__":
    sys.exit(main())
