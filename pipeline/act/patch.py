"""Патчит worldofhorror.exe, чтобы он показывал переведённый текст, не меняя ни одного значения, которое использует логика игры.

Использование: python -I pipeline/act/patch.py [--game DIR] [--output EXE] [--strings FILE] [--literal]   (обычно запускается `woh.py build`)

Входной файл никогда не изменяется. Таблицы, которые он читает, создаёт woh.py для этой точной сборки, в кэше сборки. Изменения:

1. Подписи урона в бою: записи документа `DOOM`, `STA`, `REA` и `ALL` задают текст, который показывают боевые события отрисовки для каждого
   типа урона (логические литералы с теми же именами не трогаются). Если хотя бы одна переведена, охранное условие `if (language == 7)` блока подстановки подписей в трёх событиях отрисовки заменяется на NOP,
   а 12 загрузок при запуске, которые подают строки подписей этого блока, перенаправляются (patch_sites.tsv); пустая запись оставляет английский ключ как подпись.
2. Перевод во время отрисовки (по умолчанию): каждая другая непустая строка `source|translation` становится записью хеш-таблицы. 16
   встроенных функций, которые рисуют или измеряют текст (draw_text*, string_width*, string_height*; draw_hooks.tsv), перенаправляются на заглушки, которые на время вызова заменяют текстовый аргумент его переводом и после вызова возвращают оригинал, поэтому значения,
   которые сравнивает и сохраняет игра, никогда не меняются. Перевести можно только строку, переданную целиком одной из этих встроенных функций.
3. `--literal` (необязательно): дополнительно перенаправляет каждую ссылку кода на собственные копии исходного текста exe (refs.tsv), но только
   для текстов, которые никакой код не сравнивает (usage.tsv, class != logic). Это также затрагивает текст, который строится или изменяется до отрисовки, ценой гарантии для этих текстов.

Новый текст, таблица и хук находятся в двух добавленных секциях: `.ruloc` (данные для чтения и записи) и `.ruhook` (код). Всё использует
относительные адреса; ссылка хука на таблицу разрешается здесь (hook.json). Запись unwind для хука добавляется в
`.pdata`. Каждый исходный байт проверяется перед изменением. Если менять нечего, результат — идентичная копия.
"""
import argparse
import ast
import json
import pathlib
import struct
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "generate" / "hook")]  # -I does not add the script directory
import common
import table
from common import LABEL_KEYS, SEPARATOR, unescape

IMAGE_BASE = 0x140000000
FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000
DATA_FLAGS, CODE_FLAGS = 0xC0000040, 0x60000020  # initialized data read/write; code execute/read
UNWIND_ALLOC_0x48 = bytes([0x01, 0x04, 0x01, 0x00, 0x04, 0x82, 0x00, 0x00])  # prolog `sub rsp,0x48` (4 bytes), one code, padded


def align(value, to):
    return (value + to - 1) // to * to


class Pool:
    """Bytes appended to the new data section; hands out VAs. Text is deduplicated."""

    def __init__(self, base_va):
        self.base_va, self.data, self.cache = base_va, bytearray(), {}

    def add(self, text):
        if text not in self.cache:
            self.cache[text] = self.add_bytes(text.encode("utf-8") + b"\0", 1)
        return self.cache[text]

    def add_bytes(self, blob, alignment):
        self.data += b"\0" * (-len(self.data) % alignment)
        va = self.base_va + len(self.data)
        self.data += blob
        return va


def read_translations(path):
    translations = {}
    with open(path, encoding="utf-8", newline="\n") as file:
        for number, line in enumerate(file, 1):
            line = line.rstrip("\r\n")  # CRLF documents: control characters inside strings are escaped, so none is real
            if not line:
                continue
            source, separator, translation = line.partition(SEPARATOR)
            if not separator:
                raise SystemExit(f"{path}:{number}: missing {SEPARATOR}")
            if translation:
                translations[unescape(source)] = unescape(translation)
    return translations


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as file:
        return [line.rstrip("\n").split("\t") for line in file if line.strip()]


def main(src, dst, tables, strings_path=None, literal=False):
    """Write the patched exe to dst. Returns False when nothing changed (dst is then an identical copy of src)."""
    data = bytearray(pathlib.Path(src).read_bytes())

    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    sec_table = opt + struct.unpack_from("<H", data, pe + 20)[0]
    sections = [struct.unpack_from("<8sIIII", data, sec_table + 40 * i) for i in range(nsec)]

    def to_offset(va):
        rva = va - IMAGE_BASE
        for _, vsize, vaddr, rsize, rptr in sections:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return rptr + rva - vaddr
        raise ValueError(f"VA {va:#x} not in any section")

    first_free_rva = max(vaddr + align(max(vs, rs), SECT_ALIGN) for _, vs, vaddr, rs, _ in sections)
    pool = Pool(IMAGE_BASE + first_free_rva)  # the data section comes first, so its VAs are known from the start

    def repoint(lea_va, length, expected_hex, target_va, new_va):
        """Rewrite the disp32 of a verified RIP-relative LEA so it loads new_va instead of target_va."""
        off = to_offset(lea_va)
        original = data[off:off + length]
        assert original.hex() == expected_hex, f"LEA {lea_va:#x} bytes differ from the export"
        assert length == 7 and original[0] in (0x48, 0x4C) and original[1] == 0x8D and original[2] & 0xC7 == 0x05, \
            f"LEA {lea_va:#x} is not a RIP-relative lea"
        assert lea_va + length + struct.unpack_from("<i", original, 3)[0] == target_va, f"LEA {lea_va:#x} target differs"
        struct.pack_into("<i", data, off + 3, new_va - (lea_va + length))

    translations = read_translations(strings_path) if strings_path else {}

    # 1. battle labels
    if any(translations.get(key) for key in LABEL_KEYS):
        rows = read_tsv(tables / "patch_sites.tsv")
        guards = [row for row in rows if row[0] == "guard"]
        slots = [row for row in rows if row[0] == "slot"]
        if len(guards) != 3 or len(slots) != 12:
            raise SystemExit(f"expected 3 guards and 12 slots, got {len(guards)} and {len(slots)}")
        for _, addr, length, expected, _ in guards:
            off = to_offset(int(addr, 16))
            assert data[off:off + int(length)].hex() == expected, f"guard {addr} bytes differ"
            data[off:off + int(length)] = b"\x90" * int(length)
        for index, (_, _slot, lea, length, expected, literal_va, _text) in enumerate(slots):
            key = LABEL_KEYS[index % 4]
            repoint(int(lea, 16), int(length), expected, int(literal_va, 16), pool.add(translations.get(key) or key))
        print("labels: " + ", ".join(f"{key}={translations.get(key) or key}" for key in LABEL_KEYS))
    else:
        print("labels: all empty, left unchanged")

    texts = {text: translation for text, translation in translations.items() if text not in LABEL_KEYS}

    # 3. optional literal replacement, restricted to texts no code compares
    if literal and texts:
        classes = {}
        for row in read_tsv(tables / "usage.tsv")[1:]:
            classes[ast.literal_eval(row[5])] = row[0]
        copies = {}
        for va, text in read_tsv(tables / "targets.tsv"):
            copies[int(va, 16)] = unescape(text)
        refs = defaultdict(list)
        for va, from_va, kind, length, hexbytes in read_tsv(tables / "refs.tsv"):
            refs[int(va, 16)].append((int(from_va, 16), kind, int(length), hexbytes))
        loads, skipped_logic = Counter(), []
        for target_va, text in copies.items():
            if text not in texts:
                continue
            if classes.get(text) == "logic":
                skipped_logic.append(text)
                continue
            new_va = pool.add(texts[text])
            for from_va, kind, length, hexbytes in refs[target_va]:
                if kind == "LEA":  # other kinds are value-propagation entries, not address loads
                    repoint(from_va, length, hexbytes, target_va, new_va)
                    loads[text] += 1
        print(f"literal: {len(loads)} texts, {sum(loads.values())} loads repointed; "
              f"{len(set(skipped_logic))} compared texts left to the draw hook")

    # 2. draw-time translation
    hook_sites = []
    if texts:
        table_va = pool.add_bytes(table.build_table(texts), 16)
        unwind_va = pool.add_bytes(UNWIND_ALLOC_0x48, 4)
        hook_sites = read_tsv(tables / "draw_hooks.tsv")
        print(f"hook: {len(texts)} texts in the table, {len(hook_sites)} built-ins hooked")
    has_code = bool(hook_sites)

    if not pool.data:
        # a zero-size section makes the image invalid (loader error 193), so add none
        pathlib.Path(dst).write_bytes(data)
        print(f"wrote {dst}: nothing to change, identical to the input")
        return False

    last_end = max(rptr + rsize for _, _, _, rsize, rptr in sections)
    header_off = sec_table + 40 * nsec
    first_raw = min(rptr for *_, rptr in sections)
    new_sections = 2 if has_code else 1
    assert header_off + 40 * new_sections <= first_raw and last_end == len(data), "no header room or trailing data"

    data_rva, data_size = first_free_rva, len(pool.data)
    code = bytearray()
    code_rva = data_rva + align(data_size, SECT_ALIGN)
    if has_code:
        meta = json.loads((tables / "hook.json").read_text())
        common_code = bytearray((tables / "hook.bin").read_bytes())
        assert common_code[:4] == b"\x48\x83\xec\x48", "UNWIND_ALLOC_0x48 describes a prolog of exactly `sub rsp,0x48`"
        for reloc in meta["relocations"]:
            assert reloc["symbol"] == "g_table", f"unresolved hook symbol {reloc['symbol']}"
            struct.pack_into("<i", common_code, reloc["offset"], (table_va - IMAGE_BASE) - (code_rva + reloc["offset"] + 4))
        code += common_code
        code += b"\xcc" * (-len(code) % 16)
        stubs_off = len(code)
        infos_off = stubs_off + 16 * len(hook_sites)
        stubs, infos = bytearray(), bytearray()
        for n, (name, arg_index, lea, length, expected, function) in enumerate(hook_sites):
            repoint_target = int(function, 16)
            stub_rva = code_rva + stubs_off + 16 * n
            info_rva = code_rva + infos_off + 8 * n
            stubs += table.stub(stub_rva, info_rva, code_rva + meta["symbols"]["common"])
            infos += table.info(info_rva, repoint_target - IMAGE_BASE, int(arg_index))
            repoint(int(lea, 16), int(length), expected, repoint_target, IMAGE_BASE + stub_rva)
        code += stubs + infos

    # headers
    def add_section(index, name, virtual_size, rva, raw_ptr, flags):
        raw_size = align(virtual_size, FILE_ALIGN)
        data[header_off + 40 * index:header_off + 40 * index + 40] = struct.pack(
            "<8sIIIIIIHHI", name, virtual_size, rva, raw_size, raw_ptr, 0, 0, 0, 0, flags)
        return raw_size

    data_raw = add_section(0, b".ruloc", data_size, data_rva, last_end, DATA_FLAGS)
    body = bytes(pool.data) + b"\0" * (data_raw - data_size)
    size_of_image = data_rva + align(data_size, SECT_ALIGN)
    if has_code:
        code_raw = add_section(1, b".ruhook", len(code), code_rva, last_end + data_raw, CODE_FLAGS)
        body += bytes(code) + b"\0" * (code_raw - len(code))
        size_of_image = code_rva + align(len(code), SECT_ALIGN)

        # unwind entry so an exception passing through the hook can be unwound: append to .pdata, which sorts by address
        entries = struct.pack("<III", code_rva, code_rva + meta["symbols"]["common_end"], unwind_va - IMAGE_BASE)
        dir_off = opt + 112 + 3 * 8
        pdata_rva, pdata_size = struct.unpack_from("<II", data, dir_off)
        for index, (_, vsize, vaddr, rsize, rptr) in enumerate(sections):
            if vaddr == pdata_rva:
                assert pdata_size + len(entries) <= rsize and vsize + len(entries) <= align(vsize, SECT_ALIGN), ".pdata has no room"
                assert struct.unpack_from("<I", data, rptr + pdata_size - 12)[0] < code_rva, ".pdata is not sorted below the hook"
                data[rptr + pdata_size:rptr + pdata_size + len(entries)] = entries
                struct.pack_into("<I", data, sec_table + 40 * index + 8, vsize + len(entries))  # VirtualSize
                break
        else:
            raise SystemExit("exception directory is not inside any section")
        struct.pack_into("<I", data, dir_off + 4, pdata_size + len(entries))

    struct.pack_into("<H", data, pe + 6, nsec + new_sections)
    struct.pack_into("<I", data, opt + 56, size_of_image)
    data += body
    pathlib.Path(dst).write_bytes(data)
    print(f"wrote {dst}: .ruloc at RVA {data_rva:#x} ({data_size} bytes)" + (f", .ruhook at RVA {code_rva:#x} ({len(code)} bytes)" if has_code else ""))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", help="папка игры (по умолчанию установка Steam)")
    parser.add_argument("--output", type=pathlib.Path, default=common.OUTPUT / common.EXE)
    parser.add_argument("--strings", type=pathlib.Path, default=common.TRANSLATION / "exe_strings.txt")
    parser.add_argument("--literal", action="store_true", help="также перенаправить собственные копии текстов exe, которые код не сравнивает")
    arguments = parser.parse_args()
    game = common.game_dir(arguments.game)
    common.require_pristine_game(game)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    if main(game / common.EXE, arguments.output, common.cache_dir(game) / "out", arguments.strings, arguments.literal):
        common.record_produced(arguments.output)  # an identical copy is the original game file, not our output
