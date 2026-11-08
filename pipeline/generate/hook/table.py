"""The translation table the hook reads (layout described in hook.s) and the 16-byte stubs that go into it."""

import struct

FNV_OFFSET, FNV_PRIME = 0x811C9DC5, 0x01000193


def fnv1a(data):
    value = FNV_OFFSET
    for byte in data:
        value = ((value ^ byte) * FNV_PRIME) & 0xFFFFFFFF
    return value


def build_table(translations):
    """translations: {original text: translated text}. Returns the bytes of the table + keys + texts + string objects.

    Offsets inside are relative to the first byte (g_table), so the blob can sit at any address.
    """
    count = 4
    while count < 2 * max(len(translations), 1):
        count *= 2
    header = 16 + 16 * count
    body = bytearray()
    entries = [None] * count
    for original, translated in translations.items():
        key, text = original.encode("utf-8") + b"\0", translated.encode("utf-8") + b"\0"
        key_off = header + len(body)
        body += key
        text_off = header + len(body)
        body += text
        body += b"\0" * (-(header + len(body)) % 8)
        refstring_off = header + len(body)
        body += struct.pack(
            "<QII", 0, 1, (len(text) - 1) | 0x80000000
        )  # text pointer is filled in by the hook
        slot = fnv1a(key[:-1]) & (count - 1)
        while entries[slot] is not None:
            slot = (slot + 1) & (count - 1)
        entries[slot] = (fnv1a(key[:-1]), key_off, refstring_off, text_off)
    table = struct.pack("<IIII", count - 1, 0, 0, 0)
    for entry in entries:
        table += struct.pack("<IIII", *(entry or (0, 0, 0, 0)))
    return table + bytes(body)


def stub(stub_va, info_va, common_va):
    """lea r10,[info]; jmp common; padded to 16 bytes (addresses are VAs or RVAs of the same base)."""
    lea = b"\x4c\x8d\x15" + struct.pack("<i", info_va - (stub_va + 7))
    jmp = b"\xe9" + struct.pack("<i", common_va - (stub_va + 12))
    return (lea + jmp).ljust(16, b"\xcc")


def info(info_va, original_va, arg_index):
    return struct.pack("<ii", original_va - info_va, arg_index)
