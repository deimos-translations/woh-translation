"""Patch worldofhorror.exe so it shows translated text without changing any value the game logic uses.

Usage: python -I re/patch.py <input exe> <output exe> [strings.txt] [--literal]

The input file is never modified; it must be the build recorded in re/build.md5. Three independent changes:

1. Battle damage labels: the strings.txt entries `DOOM`, `STA`, `REA` and `ALL` set the text the combat draw events show for each
   damage type (the logic literals of the same name are not touched). If any is translated, the `if (language == 7)` guard of the
   label-substitution block in the three draw events is NOPed and the 12 startup loads feeding that block's label strings are
   repointed (re/patch_sites.tsv); an empty entry keeps its English key as the label.
2. Draw-time translation (default): every other non-empty `source<#>translation` line becomes an entry of a hash table. The 16
   built-ins that draw or measure text (draw_text*, string_width*, string_height*; re/draw_hooks.tsv) are pointed at stubs that
   replace the text argument by its translation for the duration of the call and put the original back afterwards, so the values
   the game compares and stores are never changed. Only a string passed whole to one of those built-ins can be translated.
3. `--literal` (optional): additionally repoints every code reference to the exe's own copies of the source text
   (re/strings/refs.tsv), but only for texts that no code compares (re/strings/usage.tsv, class != logic). This also reaches text
   that is built or modified before drawing, at the cost of the guarantee for those texts.

New text, the table and the hook live in two appended sections: `.ruloc` (read/write data) and `.ruhook` (code). Everything uses
relative addresses, so address-space randomisation needs no relocations. An unwind entry for the hook is appended to `.pdata`.
Every original byte is verified before it is changed. If there is nothing to change, the output is an identical copy.
"""
import argparse
import ast
import hashlib
import json
import pathlib
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE / "hook"))
import table  # noqa: E402

LABEL_KEYS = ["DOOM", "STA", "REA", "ALL"]  # per draw event, in re/patch_sites.tsv order; same list in re/strings.py
IMAGE_BASE = 0x140000000
FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000
SEPARATOR = "<#>"
UNESCAPES = {"\\\\": "\\", "\\r": "\r", "\\n": "\n", "\\t": "\t"}
DATA_FLAGS, CODE_FLAGS = 0xC0000040, 0x60000020  # initialized data read/write; code execute/read
UNWIND_ALLOC_0x48 = bytes([0x01, 0x04, 0x01, 0x00, 0x04, 0x82, 0x00, 0x00])  # prolog `sub rsp,0x48` (4 bytes), one code, padded


def align(value, to):
    return (value + to - 1) // to * to


def unescape(text):
    return re.sub(r"\\[\\rnt]", lambda match: UNESCAPES[match.group()], text)


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
    for number, line in enumerate(open(path, encoding="utf-8", newline="\n"), 1):
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
    return [line.rstrip("\n").split("\t") for line in open(HERE / path, encoding="utf-8", newline="") if line.strip()]


def main(src, dst, strings_path=None, literal=False):
    data = bytearray(open(src, "rb").read())
    expected_md5 = (HERE / "build.md5").read_text(encoding="utf-8").strip()
    actual_md5 = hashlib.md5(data).hexdigest()
    if actual_md5 != expected_md5:
        raise SystemExit(
            f"{src} is not the build the patch files were made for (md5 {actual_md5}, expected {expected_md5}).\n"
            "The game was updated or the file was modified: re-analyse it and regenerate re/patch_sites.tsv, re/draw_hooks.tsv "
            "and re/strings/ (see re/NOTES.md, 'After a game update').")

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
        rows = read_tsv("patch_sites.tsv")
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
        for row in read_tsv("strings/usage.tsv")[1:]:
            classes[ast.literal_eval(row[5])] = row[0]
        copies = {}
        for va, text in read_tsv("strings/targets.tsv"):
            copies[int(va, 16)] = unescape(text)
        refs = defaultdict(list)
        for va, from_va, kind, length, hexbytes in read_tsv("strings/refs.tsv"):
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
        hook_sites = read_tsv("draw_hooks.tsv")
        blob = table.build_table(texts)
        table_va = pool.add_bytes(blob, 16)
        unwind_va = pool.add_bytes(UNWIND_ALLOC_0x48, 4)
        print(f"hook: {len(texts)} texts in the table, {len(hook_sites)} built-ins hooked")

    if not pool.data:
        # a zero-size section makes the image invalid (loader error 193), so add none
        open(dst, "wb").write(data)
        print(f"wrote {dst}: nothing to change, identical to the input")
        return

    last_end = max(rptr + rsize for _, _, _, rsize, rptr in sections)
    header_off = sec_table + 40 * nsec
    first_raw = min(rptr for *_, rptr in sections)
    new_sections = 2 if hook_sites else 1
    assert header_off + 40 * new_sections <= first_raw and last_end == len(data), "no header room or trailing data"

    data_rva, data_size = first_free_rva, len(pool.data)
    code = bytearray()
    code_rva = data_rva + align(data_size, SECT_ALIGN)
    if hook_sites:
        meta = json.loads((HERE / "hook" / "hook.json").read_text())
        common = bytearray((HERE / "hook" / "hook.bin").read_bytes())
        assert common[:4] == b"\x48\x83\xec\x48", "UNWIND_ALLOC_0x48 describes a prolog of exactly `sub rsp,0x48`"
        (reloc,) = [r for r in meta["relocations"] if r["symbol"] == "g_table"]
        struct.pack_into("<i", common, reloc["offset"], (table_va - IMAGE_BASE) - (code_rva + reloc["offset"] + 4))
        code += common
        code += b"\xcc" * (-len(code) % 16)
        stubs_off = len(code)
        infos_off = stubs_off + 16 * len(hook_sites)
        stubs, infos = bytearray(), bytearray()
        for n, (name, arg_index, lea, length, expected, function) in enumerate(hook_sites):
            repoint_target = int(function, 16)
            stub_rva = code_rva + stubs_off + 16 * n
            info_rva = code_rva + infos_off + 8 * n
            stubs += table.stub(stub_rva, info_rva, code_rva)
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
    if hook_sites:
        code_raw = add_section(1, b".ruhook", len(code), code_rva, last_end + data_raw, CODE_FLAGS)
        body += bytes(code) + b"\0" * (code_raw - len(code))
        size_of_image = code_rva + align(len(code), SECT_ALIGN)

        # unwind entry so an exception passing through the hook can be unwound: append to .pdata, which sorts by address
        dir_off = opt + 112 + 3 * 8
        pdata_rva, pdata_size = struct.unpack_from("<II", data, dir_off)
        entry = struct.pack("<III", code_rva, code_rva + len(common), unwind_va - IMAGE_BASE)
        for index, (_, vsize, vaddr, rsize, rptr) in enumerate(sections):
            if vaddr == pdata_rva:
                assert pdata_size + 12 <= rsize and vsize + 12 <= align(vsize, SECT_ALIGN), ".pdata has no room for one entry"
                assert struct.unpack_from("<I", data, rptr + pdata_size - 12)[0] < code_rva, ".pdata is not sorted below the hook"
                data[rptr + pdata_size:rptr + pdata_size + 12] = entry
                struct.pack_into("<I", data, sec_table + 40 * index + 8, vsize + 12)  # VirtualSize
                break
        else:
            raise SystemExit("exception directory is not inside any section")
        struct.pack_into("<I", data, dir_off + 4, pdata_size + 12)

    struct.pack_into("<H", data, pe + 6, nsec + new_sections)
    struct.pack_into("<I", data, opt + 56, size_of_image)
    data += body
    open(dst, "wb").write(data)
    print(f"wrote {dst}: .ruloc at RVA {data_rva:#x} ({data_size} bytes)" + (f", .ruhook at RVA {code_rva:#x} ({len(code)} bytes)" if hook_sites else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("strings", nargs="?")
    parser.add_argument("--literal", action="store_true", help="also repoint the exe's own copies of texts no code compares")
    arguments = parser.parse_args()
    main(arguments.input, arguments.output, arguments.strings, arguments.literal)
