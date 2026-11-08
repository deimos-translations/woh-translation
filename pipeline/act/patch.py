"""Patches worldofhorror.exe to show translated text without changing any value the game logic uses.

Usage: python -I pipeline/act/patch.py [--game DIR] [--output EXE] [--strings FILE]   (usually run by `woh.py build`)

The input file is never modified. The tables it reads are made by woh.py for this exact build, in the build cache. Changes:

1. Combat damage labels: the document entries `DOOM`, `STA`, `REA` and `ALL` set the text the combat draw events show for each
   damage type (logic literals with the same names are not touched). If at least one is translated, the `if (language == 7)` guard of the label substitution block in the three draw events is replaced with NOPs,
   and the 12 startup loads that feed the label strings of that block are redirected (patch_sites.tsv); an empty entry keeps the English key as the label.
2. Draw-time translation (default): every other non-empty `source|translation` line becomes a hash table entry. The 16
   built-in functions that draw or measure text (draw_text*, string_width*, string_height*; draw_hooks.tsv) are redirected to stubs that, for the duration of the call, replace the text argument with its translation and restore the original afterwards, so the values
   the game compares and saves are never changed. Only a string passed whole to one of these built-ins can be translated.
3. Document lines marked with a leading `!` (`!source|translation`): additionally redirects every code reference to the exe's own copies of the
   source text (refs.tsv). This also affects text that is built or modified before drawing, at the cost of the guarantee for those texts.
   A marked string that the code compares (usage.tsv, class == logic) stops the patch: substituting it breaks the game logic.

The new text, the table and the hook live in two added sections: `.ruloc` (read/write data) and `.ruhook` (code). Everything uses
relative addresses; the hook's reference to the table is resolved here (hook.json). An unwind entry for the hook is added to
`.pdata`. Every original byte is verified before it is changed. If there is nothing to change, the result is an identical copy.
"""

import argparse
import ast
import json
import pathlib
import struct
import sys
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [
    str(HERE.parent),
    str(HERE.parent / "generate" / "hook"),
]  # -I does not add the script directory
import common
import table
from common import LABEL_KEYS, SEPARATOR, unescape

IMAGE_BASE = 0x140000000
FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000
DATA_FLAGS, CODE_FLAGS = (
    0xC0000040,
    0x60000020,
)  # initialized data read/write; code execute/read
UNWIND_ALLOC_0x48 = bytes(
    [0x01, 0x04, 0x01, 0x00, 0x04, 0x82, 0x00, 0x00]
)  # prolog `sub rsp,0x48` (4 bytes), one code, padded


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
    """-> ({source: translation}, sources marked for literal replacement); entries without a translation are left out of both."""
    translations, marked = {}, set()
    with pathlib.Path(path).open(encoding="utf-8", newline="\n") as file:
        for number, raw_line in enumerate(file, 1):
            # CRLF documents: control characters inside strings are escaped, so none is real
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            literal, source, separator, translation = common.parse_entry(line)
            if not separator:
                raise SystemExit(f"{path}:{number}: missing {SEPARATOR}")
            if translation:
                source = unescape(source)
                if source in translations:
                    raise SystemExit(f"{path}:{number}: duplicate {source!r}")
                translations[source] = unescape(translation)
                if literal:
                    marked.add(source)
    return translations, marked


def read_tsv(path):
    with pathlib.Path(path).open(encoding="utf-8", newline="") as file:
        return [line.rstrip("\n").split("\t") for line in file if line.strip()]


def main(src, dst, tables, strings_path=None):
    """Write the patched exe to dst. Returns False when nothing changed (dst is then an identical copy of src)."""
    data = bytearray(pathlib.Path(src).read_bytes())

    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    sec_table = opt + struct.unpack_from("<H", data, pe + 20)[0]
    sections = [
        struct.unpack_from("<8sIIII", data, sec_table + 40 * i) for i in range(nsec)
    ]

    def to_offset(va):
        rva = va - IMAGE_BASE
        for _, vsize, vaddr, rsize, rptr in sections:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return rptr + rva - vaddr
        raise ValueError(f"VA {va:#x} not in any section")

    first_free_rva = max(
        vaddr + align(max(vs, rs), SECT_ALIGN) for _, vs, vaddr, rs, _ in sections
    )
    pool = Pool(
        IMAGE_BASE + first_free_rva
    )  # the data section comes first, so its VAs are known from the start

    def repoint(lea_va, length, expected_hex, target_va, new_va):
        """Rewrite the disp32 of a verified RIP-relative LEA so it loads new_va instead of target_va."""
        off = to_offset(lea_va)
        original = data[off : off + length]
        assert original.hex() == expected_hex, (
            f"LEA {lea_va:#x} bytes differ from the export"
        )
        assert (
            length == 7
            and original[0] in (0x48, 0x4C)
            and original[1] == 0x8D
            and original[2] & 0xC7 == 0x05
        ), f"LEA {lea_va:#x} is not a RIP-relative lea"
        assert (
            lea_va + length + struct.unpack_from("<i", original, 3)[0] == target_va
        ), f"LEA {lea_va:#x} target differs"
        struct.pack_into("<i", data, off + 3, new_va - (lea_va + length))

    translations, marked = (
        read_translations(strings_path) if strings_path else ({}, set())
    )
    marked -= set(LABEL_KEYS)
    if marked:  # refuse before changing anything
        classes = {}
        for row in read_tsv(tables / "usage.tsv")[1:]:
            classes[ast.literal_eval(row[5])] = row[0]
        compared = sorted(text for text in marked if classes.get(text) == "logic")
        if compared:
            raise SystemExit(
                "marked `!` but compared by the game (usage.tsv: logic), remove the mark:\n"
                + "\n".join(f"  {common.escape(text)}" for text in compared)
            )

    # 1. battle labels
    if any(translations.get(key) for key in LABEL_KEYS):
        rows = read_tsv(tables / "patch_sites.tsv")
        guards = [row for row in rows if row[0] == "guard"]
        slots = [row for row in rows if row[0] == "slot"]
        if len(guards) != 3 or len(slots) != 12:
            raise SystemExit(
                f"expected 3 guards and 12 slots, got {len(guards)} and {len(slots)}"
            )
        for _, addr, length, expected, _ in guards:
            off = to_offset(int(addr, 16))
            assert data[off : off + int(length)].hex() == expected, (
                f"guard {addr} bytes differ"
            )
            data[off : off + int(length)] = b"\x90" * int(length)
        for index, (_, _slot, lea, length, expected, literal_va, _text) in enumerate(
            slots
        ):
            key = LABEL_KEYS[index % 4]
            repoint(
                int(lea, 16),
                int(length),
                expected,
                int(literal_va, 16),
                pool.add(translations.get(key) or key),
            )
        print(
            "labels: "
            + ", ".join(f"{key}={translations.get(key) or key}" for key in LABEL_KEYS)
        )
    else:
        print("labels: all empty, left unchanged")

    texts = {
        text: translation
        for text, translation in translations.items()
        if text not in LABEL_KEYS
    }

    # 3. literal replacement of the marked entries (checked above)
    if marked:
        refs = defaultdict(list)
        for va, from_va, kind, length, hexbytes in read_tsv(tables / "refs.tsv"):
            refs[int(va, 16)].append((int(from_va, 16), kind, int(length), hexbytes))
        loads = Counter()
        for va, escaped in read_tsv(tables / "targets.tsv"):
            text = unescape(escaped)
            if text not in marked:
                continue
            target_va, new_va = int(va, 16), pool.add(texts[text])
            for from_va, kind, length, hexbytes in refs[target_va]:
                if (
                    kind == "LEA"
                ):  # other kinds are value-propagation entries, not address loads
                    repoint(from_va, length, hexbytes, target_va, new_va)
                    loads[text] += 1
        print(
            f"literal: {len(loads)} marked texts, {sum(loads.values())} loads repointed"
        )
        for text in sorted(marked - loads.keys()):
            print(f"  marked, no code copy in this build: {common.escape(text)}")

    # 2. draw-time translation
    hook_sites = []
    if texts:
        table_va = pool.add_bytes(table.build_table(texts), 16)
        unwind_va = pool.add_bytes(UNWIND_ALLOC_0x48, 4)
        hook_sites = read_tsv(tables / "draw_hooks.tsv")
        print(
            f"hook: {len(texts)} texts in the table, {len(hook_sites)} built-ins hooked"
        )
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
    assert header_off + 40 * new_sections <= first_raw and last_end == len(data), (
        "no header room or trailing data"
    )

    data_rva, data_size = first_free_rva, len(pool.data)
    code = bytearray()
    code_rva = data_rva + align(data_size, SECT_ALIGN)
    if has_code:
        meta = json.loads((tables / "hook.json").read_text())
        common_code = bytearray((tables / "hook.bin").read_bytes())
        assert common_code[:4] == b"\x48\x83\xec\x48", (
            "UNWIND_ALLOC_0x48 describes a prolog of exactly `sub rsp,0x48`"
        )
        for reloc in meta["relocations"]:
            assert reloc["symbol"] == "g_table", (
                f"unresolved hook symbol {reloc['symbol']}"
            )
            struct.pack_into(
                "<i",
                common_code,
                reloc["offset"],
                (table_va - IMAGE_BASE) - (code_rva + reloc["offset"] + 4),
            )
        code += common_code
        code += b"\xcc" * (-len(code) % 16)
        stubs_off = len(code)
        infos_off = stubs_off + 16 * len(hook_sites)
        stubs, infos = bytearray(), bytearray()
        for n, (_name, arg_index, lea, length, expected, function) in enumerate(
            hook_sites
        ):
            repoint_target = int(function, 16)
            stub_rva = code_rva + stubs_off + 16 * n
            info_rva = code_rva + infos_off + 8 * n
            stubs += table.stub(
                stub_rva, info_rva, code_rva + meta["symbols"]["common"]
            )
            infos += table.info(info_rva, repoint_target - IMAGE_BASE, int(arg_index))
            repoint(
                int(lea, 16),
                int(length),
                expected,
                repoint_target,
                IMAGE_BASE + stub_rva,
            )
        code += stubs + infos

    # headers
    def add_section(index, name, virtual_size, rva, raw_ptr, flags):
        raw_size = align(virtual_size, FILE_ALIGN)
        data[header_off + 40 * index : header_off + 40 * index + 40] = struct.pack(
            "<8sIIIIIIHHI",
            name,
            virtual_size,
            rva,
            raw_size,
            raw_ptr,
            0,
            0,
            0,
            0,
            flags,
        )
        return raw_size

    data_raw = add_section(0, b".ruloc", data_size, data_rva, last_end, DATA_FLAGS)
    body = bytes(pool.data) + b"\0" * (data_raw - data_size)
    size_of_image = data_rva + align(data_size, SECT_ALIGN)
    if has_code:
        code_raw = add_section(
            1, b".ruhook", len(code), code_rva, last_end + data_raw, CODE_FLAGS
        )
        body += bytes(code) + b"\0" * (code_raw - len(code))
        size_of_image = code_rva + align(len(code), SECT_ALIGN)

        # unwind entry so an exception passing through the hook can be unwound: append to .pdata, which sorts by address
        entries = struct.pack(
            "<III",
            code_rva,
            code_rva + meta["symbols"]["common_end"],
            unwind_va - IMAGE_BASE,
        )
        dir_off = opt + 112 + 3 * 8
        pdata_rva, pdata_size = struct.unpack_from("<II", data, dir_off)
        for index, (_, vsize, vaddr, rsize, rptr) in enumerate(sections):
            if vaddr == pdata_rva:
                assert pdata_size + len(entries) <= rsize and vsize + len(
                    entries
                ) <= align(vsize, SECT_ALIGN), ".pdata has no room"
                assert (
                    struct.unpack_from("<I", data, rptr + pdata_size - 12)[0] < code_rva
                ), ".pdata is not sorted below the hook"
                data[rptr + pdata_size : rptr + pdata_size + len(entries)] = entries
                struct.pack_into(
                    "<I", data, sec_table + 40 * index + 8, vsize + len(entries)
                )  # VirtualSize
                break
        else:
            raise SystemExit("exception directory is not inside any section")
        struct.pack_into("<I", data, dir_off + 4, pdata_size + len(entries))

    struct.pack_into("<H", data, pe + 6, nsec + new_sections)
    struct.pack_into("<I", data, opt + 56, size_of_image)
    data += body
    pathlib.Path(dst).write_bytes(data)
    print(
        f"wrote {dst}: .ruloc at RVA {data_rva:#x} ({data_size} bytes)"
        + (f", .ruhook at RVA {code_rva:#x} ({len(code)} bytes)" if has_code else "")
    )
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game", help="game folder (default: the Steam install)")
    parser.add_argument(
        "--output", type=pathlib.Path, default=common.OUTPUT / common.EXE
    )
    parser.add_argument(
        "--strings", type=pathlib.Path, default=common.TRANSLATION / "exe_strings.txt"
    )
    arguments = parser.parse_args()
    game = common.game_dir(arguments.game)
    common.require_pristine_game(game)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    if main(
        game / common.EXE,
        arguments.output,
        common.cache_dir(game) / "out",
        arguments.strings,
    ):
        common.record_produced(
            arguments.output
        )  # an identical copy is the original game file, not our output
