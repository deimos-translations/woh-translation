"""Проверяет хук пропатченного exe, запуская его собственные заглушки, таблицу и код (не игру) против фиктивной встроенной функции.

Использование: python -I pipeline/check/check_patched.py <patched exe> <exe_strings.txt> <draw_hooks.tsv> <hook.json>   (только Windows)

Для каждой из 16 перехваченных встроенных функций: декодирует перенаправленный `lea rdx,[function]`, чтобы найти её заглушку, отображает секции `.ruloc` и `.ruhook` exe по их реальным относительным позициям в исполняемой памяти, направляет данные заглушки на фиктивную встроенную функцию и вызывает заглушку с
переведённым текстом, непереведённым текстом и не-строкой. Также проверяет запись unwind `.pdata` для хука.
"""
import ctypes
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # -I does not add the script directory
import common
import test_hook

IMAGE_BASE = 0x140000000


def main(exe_path, strings_path, hooks_path, meta_path):
    data = pathlib.Path(exe_path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    sec_table = opt + struct.unpack_from("<H", data, pe + 20)[0]
    sections = {}
    for i in range(nsec):
        name, vsize, rva, rsize, raw = struct.unpack_from("<8sIIII", data, sec_table + 40 * i)
        sections[name.rstrip(b"\0").decode()] = (vsize, rva, rsize, raw)
    failures = []

    def check(name, condition, detail=""):
        print(("ok   " if condition else "FAIL ") + name + ("" if condition else f" {detail}"))
        if not condition:
            failures.append(name)

    def to_offset(rva):
        for vsize, base, rsize, raw in sections.values():
            if base <= rva < base + max(vsize, rsize):
                return raw + rva - base
        raise ValueError(hex(rva))

    translations = {}
    with open(strings_path, encoding="utf-8", newline="") as file:
        for line in file:
            _literal, source, _, translation = common.parse_entry(line.rstrip("\r\n"))
            if translation and source not in ("DOOM", "STA", "REA", "ALL"):
                translations[common.unescape(source)] = common.unescape(translation)
    assert translations, "the document has no hook translations"

    meta = json.loads(pathlib.Path(meta_path).read_text())
    dvsize, drva, _, draw = sections[".ruloc"]
    cvsize, crva, _, craw = sections[".ruhook"]
    span = crva + cvsize - drva
    region = kernel_alloc(span + 0x1000)
    ctypes.memmove(region, data[draw:draw + dvsize], dvsize)
    ctypes.memmove(region + (crva - drva), data[craw:craw + cvsize], cvsize)
    fake_off = span + 0x100
    double = test_hook.build_double()
    ctypes.memmove(region + fake_off, double, len(double))
    cap = region + fake_off + len(double) - 80

    with open(hooks_path, encoding="utf-8") as file:
        rows = [line.rstrip("\n").split("\t") for line in file]
    check("16 hooked built-ins", len(rows) == 16)
    strings = test_hook.Strings()
    prototype = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
    sample = next(iter(translations))

    def run(address, args):
        raw = (ctypes.c_char * (16 * 4))()
        for n, (value, kind) in enumerate(args):
            struct.pack_into("<QII", raw, 16 * n, value, 0, kind)
        result = prototype(address)(1, 2, 3, len(args), ctypes.addressof(raw))
        return result, struct.unpack("<10Q", ctypes.string_at(cap, 80)), [struct.unpack_from("<QII", raw, 16 * n) for n in range(len(args))]

    for name, arg_index, lea, length, _expected, function in rows:
        arg_index = int(arg_index)
        lea_off = to_offset(int(lea, 16) - IMAGE_BASE)
        disp = struct.unpack_from("<i", data, lea_off + 3)[0]
        stub_rva = int(lea, 16) - IMAGE_BASE + int(length) + disp
        check(f"{name}: lea now points into .ruhook", crva <= stub_rva < crva + cvsize, hex(stub_rva))
        stub_off = stub_rva - drva
        stub = ctypes.string_at(region + stub_off, 12)
        info_rva = stub_rva + 7 + struct.unpack_from("<i", stub, 3)[0]
        check(f"{name}: stub shape (lea r10 / jmp common)", stub[:3] == b"\x4c\x8d\x15" and stub[7] == 0xE9)
        orig_rva_stored = struct.unpack_from("<i", ctypes.string_at(region + (info_rva - drva), 8), 0)[0]
        check(f"{name}: info points at the original function {function}",
              info_rva + orig_rva_stored == int(function, 16) - IMAGE_BASE)
        check(f"{name}: text argument index", struct.unpack_from("<i", ctypes.string_at(region + (info_rva - drva), 8), 4)[0] == arg_index)
        # test only: redirect the info to the fake built-in
        ctypes.memmove(region + (info_rva - drva), struct.pack("<i", fake_off - (info_rva - drva)), 4)

        for text, expect in ((sample, translations[sample]), ("zzz not in the table", None)):
            ref = strings.make(text)
            args = [(0, 0)] * arg_index + [(ref, 1)]
            result, captured, after = run(region + stub_off, args)
            seen = test_hook.Strings.read(captured[arg_index])
            check(f"{name}: {'translated' if expect else 'untouched'} text", seen == (expect or text) and after[arg_index][0] == ref and result == 0x1234, seen)
        _, captured, after = run(region + stub_off, [(0, 0)] * arg_index + [(0, 0)])
        check(f"{name}: non-string untouched", after[arg_index][2] == 0)

    # unwind entry: last in .pdata, sorted after the previous entry, describing `sub rsp,0x48`
    dir_rva, dir_size = struct.unpack_from("<II", data, opt + 112 + 3 * 8)
    base = to_offset(dir_rva) + dir_size - 12
    previous, entry = (struct.unpack_from("<III", data, base - 12 + 12 * i) for i in range(2))
    check("unwind entry: sorted after the previous entry", previous[0] < crva)
    check("unwind entry: covers the hook's common routine", entry[0] == crva and entry[1] == crva + meta["symbols"]["common_end"])
    unwind = data[to_offset(entry[2]):to_offset(entry[2]) + 8]
    check("unwind info: version 1, prolog 4, 1 code, ALLOC_SMALL", unwind == bytes([1, 4, 1, 0, 4, 0x82, 0, 0]), unwind.hex())
    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED")
    return 1 if failures else 0


def kernel_alloc(size):
    address = test_hook.kernel32.VirtualAlloc(None, size, 0x3000, 0x40)
    assert address
    return address


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
