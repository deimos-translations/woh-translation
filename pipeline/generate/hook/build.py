"""Собирает hook.s в <out dir>/hook.bin + hook.json (нужен clang в PATH; woh.py запускает это в кэш сборки).

Использование: python -I pipeline/generate/hook/build.py <out dir>

hook.bin — это сырой `.text` объекта. Его перемещения — REL32 относительно таблицы, которую patch.py размещает в `.ruloc`; patch.py
их разрешает. hook.json: { "size": N, "symbols": {глобальное имя: смещение в hook.bin}, "relocations": [{"offset": o, "symbol": name}] }.
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

    symbols, index = {}, 0
    while index < nsyms:  # global symbols defined in .text: their offsets, so patch.py can find entry points
        value, section, _type, storage, aux = struct.unpack_from("<IhHBB", data, symtab + 18 * index + 8)
        if section == 1 and storage == 2:  # 1-based section 1 = .text, storage class 2 = external
            symbols[symbol_name(index)] = value
        index += 1 + aux
    for i in range(nsec):
        header = 20 + 40 * i
        name, _vs, _va, raw_size, raw_ptr, reloc_ptr, _line, nrel = struct.unpack_from("<8sIIIIIIH", data, header)
        if name.rstrip(b"\0") != b".text":
            continue
        relocations = []
        for r in range(nrel):
            offset, symbol, kind = struct.unpack_from("<IIH", data, reloc_ptr + 10 * r)
            relocations.append({"offset": offset, "symbol": symbol_name(symbol), "type": kind})
        return data[raw_ptr:raw_ptr + raw_size], relocations, symbols
    raise SystemExit("no .text section")


def assemble(source, out):
    subprocess.run(["clang", "--target=x86_64-pc-windows-msvc", "-c", str(source), "-o", str(out)], check=True)


def main(out_dir):
    out_dir = pathlib.Path(out_dir)
    with tempfile.TemporaryDirectory() as tmp:
        obj = pathlib.Path(tmp) / "hook.obj"
        assemble(HERE / "hook.s", obj)
        text, relocations, symbols = read_coff_text(obj)
    assert all(r["type"] == 4 for r in relocations), "expected only IMAGE_REL_AMD64_REL32"  # 4 = REL32
    (out_dir / "hook.bin").write_bytes(text)
    (out_dir / "hook.json").write_text(json.dumps(
        {"size": len(text), "symbols": symbols,
         "relocations": [{"offset": r["offset"], "symbol": r["symbol"]} for r in relocations]}, indent=2) + "\n")
    print(f"hook.bin {len(text)} bytes, symbols {symbols}, relocations {[(r['offset'], r['symbol']) for r in relocations]}")


if __name__ == "__main__":
    main(sys.argv[1])
