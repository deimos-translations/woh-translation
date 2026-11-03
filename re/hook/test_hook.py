"""Native test of the real assembled hook (hook.bin) against a fake built-in. Runs only this test code.

Usage: python re/hook/test_hook.py   (clang on PATH; builds the test double, runs hook.bin in executable memory)
"""
import ctypes
import json
import pathlib
import random
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import table  # noqa: E402

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.VirtualAlloc.restype = ctypes.c_void_p
kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]

STRING, NUMBER = 1, 0


def build_double():
    with tempfile.TemporaryDirectory() as tmp:
        obj = pathlib.Path(tmp) / "t.obj"
        build.assemble(HERE / "hook_test.s", obj)
        text, relocations = build.read_coff_text(obj)
    assert not relocations
    return text


class Rig:
    """hook.bin + stubs + fake builtin + table, copied into one executable region (everything position independent)."""

    def __init__(self, translations, arg_indices=(0, 2)):
        self.hook = pathlib.Path(HERE / "hook.bin").read_bytes()
        meta = json.loads((HERE / "hook.json").read_text())
        assert [r["symbol"] for r in meta["relocations"]] == ["g_table"]
        self.double = build_double()
        self.base = kernel32.VirtualAlloc(None, 0x40000, 0x3000, 0x40)
        assert self.base
        self.table_off, self.double_off = 0x10000, 0x8000
        blob = bytearray(0x40000)
        hook = bytearray(self.hook)
        reloc = meta["relocations"][0]["offset"]
        struct.pack_into("<i", hook, reloc, self.table_off - (reloc + 4))
        blob[0:len(hook)] = hook
        blob[self.double_off:self.double_off + len(self.double)] = self.double
        self.cap = self.base + self.double_off + len(self.double) - 80
        data = table.build_table(translations)
        blob[self.table_off:self.table_off + len(data)] = data
        self.stubs = {}
        for n, index in enumerate(arg_indices):
            stub_off, info_off = 0x2000 + 16 * n, 0x3000 + 8 * n
            blob[stub_off:stub_off + 16] = table.stub(stub_off, info_off, 0)
            blob[info_off:info_off + 8] = table.info(info_off, self.double_off, index)
            self.stubs[index] = self.base + stub_off
        ctypes.memmove(self.base, bytes(blob), len(blob))
        self.fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)

    def call(self, index, args, argc=None):
        """args: list of (value, kind). Returns (return value, captured, args array bytes after the call)."""
        raw = (ctypes.c_char * (16 * max(len(args), 1)))()
        for n, (value, kind) in enumerate(args):
            struct.pack_into("<QII", raw, 16 * n, value, 0, kind)
        result = self.fn(self.stubs[index])(0xAAA0, 0x11, 0x22, len(args) if argc is None else argc, ctypes.addressof(raw))
        captured = ctypes.string_at(self.cap, 80)
        return result, struct.unpack("<10Q", captured), [struct.unpack_from("<QII", raw, 16 * n) for n in range(len(args))], ctypes.addressof(raw)


class Strings:
    """Keeps game-style string objects (RefString) alive for the duration of the test."""

    def __init__(self):
        self.keep = []

    def make(self, text):
        chars = ctypes.create_string_buffer(text.encode("utf-8"))
        ref = (ctypes.c_char * 16)()
        struct.pack_into("<QII", ref, 0, ctypes.addressof(chars), 1, len(text.encode()) | 0x80000000)
        self.keep += [chars, ref]
        return ctypes.addressof(ref)

    @staticmethod
    def read(ref_address):
        pointer = struct.unpack("<Q", ctypes.string_at(ref_address, 8))[0]
        return ctypes.string_at(pointer).decode("utf-8")


def main():
    strings = Strings()
    translations = {"PREP": "ПОДГ", "LOOK FOR#A WEAK SPOT": "ИЩИТЕ#СЛАБОЕ МЕСТО И ЕЩЁ ОЧЕНЬ ДЛИННОЕ ПРОДОЛЖЕНИЕ СТРОКИ",
                    "\r\n\tritual 0 0": "x", "S.ATK": "СПЕЦ"}
    rig = Rig(translations)
    failures = []

    def check(name, condition, detail=""):
        print(("ok   " if condition else "FAIL ") + name + ("" if condition else f" {detail}"))
        if not condition:
            failures.append(name)

    # 1. hit on a draw_text-style call (text at index 2)
    original = strings.make("PREP")
    ret, cap, after, args_ptr = rig.call(2, [(0, NUMBER), (0, NUMBER), (original, STRING)])
    check("hit: callee sees the translation", Strings.read(cap[2]) == "ПОДГ", Strings.read(cap[2]))
    check("hit: callee gets a different object", cap[2] != original)
    check("hit: argument restored after the call", after[2][0] == original and after[2][2] == STRING)
    check("hit: other arguments untouched", cap[0] == 0 and cap[1] == 0)
    check("hit: return value passed through", ret == 0x1234, hex(ret or 0))
    check("hit: Result/self/other/argc/args passed through",
          cap[3:8] == (0xAAA0, 0x11, 0x22, 3, args_ptr), cap[3:8])
    check("callee entry stack alignment (rsp % 16 == 8)", cap[8] % 16 == 8, hex(cap[8]))

    # 2. miss
    unknown = strings.make("NOT TRANSLATED")
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (unknown, STRING)])
    check("miss: callee sees the original", cap[2] == unknown and after[2][0] == unknown)

    # 3. text at index 0 (string_width-style), long translation, '#' kept
    original = strings.make("LOOK FOR#A WEAK SPOT")
    ret, cap, after, _ = rig.call(0, [(original, STRING)])
    check("index 0: long translation", Strings.read(cap[0]) == translations["LOOK FOR#A WEAK SPOT"], Strings.read(cap[0]))
    check("index 0: restored", after[0][0] == original)

    # 4. control characters in the key
    original = strings.make("\r\n\tritual 0 0")
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (original, STRING)])
    check("key with CR/LF/TAB", Strings.read(cap[2]) == "x")

    # 5. not a string, null string object, null characters, too few arguments
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (struct.unpack("<Q", struct.pack("<d", 3.5))[0], NUMBER)])
    check("number argument untouched", after[2][2] == NUMBER)
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (0, STRING)])
    check("null string object untouched", cap[2] == 0 and ret == 0x1234)
    empty_ref = (ctypes.c_char * 16)()
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (ctypes.addressof(empty_ref), STRING)])
    check("null character pointer untouched", cap[2] == ctypes.addressof(empty_ref) and ret == 0x1234)
    # argc 2 with index 2: args[2] does not exist; a poisoned pointer there must never be read
    ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER)], argc=2)
    check("argc <= index: nothing read, original called", ret == 0x1234 and cap[6] == 2)
    poison = (ctypes.c_char * 48)()
    struct.pack_into("<QII", poison, 32, 0xDEAD0000, 0, STRING)
    ret = rig.fn(rig.stubs[2])(1, 2, 3, 2, ctypes.addressof(poison))
    check("argc 2, poisoned args[2]: no crash", ret == 0x1234)

    # 6. many entries with collisions in a small table, hits and misses
    random.seed(7)
    words = [("w%06d" % random.randrange(10**6)) + random.choice(["", "x", "yz"]) for _ in range(400)]
    words = list(dict.fromkeys(words))
    chosen, others = words[:150], words[150:]
    big = Rig({w: "Ж" + w for w in chosen})
    bad = 0
    for w in chosen:
        ret, cap, after, _ = big.call(2, [(0, NUMBER), (0, NUMBER), (strings.make(w), STRING)])
        bad += Strings.read(cap[2]) != "Ж" + w
    check(f"{len(chosen)} translated words all hit (table of {len(table.build_table({w: w for w in chosen})) // 16} slots)", bad == 0, bad)
    bad = 0
    for w in others:
        ref = strings.make(w)
        ret, cap, after, _ = big.call(2, [(0, NUMBER), (0, NUMBER), (ref, STRING)])
        bad += cap[2] != ref
    check(f"{len(others)} untranslated words all miss", bad == 0, bad)
    # prefix / extension of a key must not match
    for text in ("PRE", "PREPP", "prep", ""):
        ref = strings.make(text)
        ret, cap, after, _ = rig.call(2, [(0, NUMBER), (0, NUMBER), (ref, STRING)])
        check(f"near miss {text!r}", cap[2] == ref)

    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
