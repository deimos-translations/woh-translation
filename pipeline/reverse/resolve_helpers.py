"""Finds the anonymous runtime helper functions of a YYC build statically, from the exe alone: `python -I resolve_helpers.py <exe> <funcmap.tsv> <symbols.json>`

Nothing is saved per build. Each helper is identified by what it is: a runtime error string it contains, its place among what other
helpers call, or how often game code calls it. Every rule must give exactly the expected result, otherwise the run stops and names the
helper: a wrong address would silently change the analysis result. If a rule stops working after a GameMaker runtime update, the rule has to change.

The output has one symbol per line, which is what Symbols.java parses."""

import bisect
import collections
import json
import pathlib
import re
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import common

BASE = 0x140000000


class Image:
    def __init__(self, path):
        self.data = data = pathlib.Path(path).read_bytes()
        self.sections = common.pe_sections(data)
        text_size, rva, raw_size, raw = self.sections[".text"]
        self.text, self.text_va = data[raw : raw + raw_size], BASE + rva
        _, rva, raw_size, raw = self.sections[".pdata"]
        ranges = {
            struct.unpack_from("<II", data, raw + at)
            for at in range(0, raw_size - 11, 12)
        }
        self.functions = sorted(
            (BASE + begin, BASE + end) for begin, end in ranges if begin
        )
        self.starts = [begin for begin, _ in self.functions]
        # shortcut: linear byte scan, so a call-shaped byte run inside an instruction counts too; rules use exact strings or large counts, which it cannot sway
        self.callers = collections.defaultdict(list)
        self.jumps = collections.defaultdict(list)
        text_end = self.text_va + text_size
        for match in re.finditer(rb"[\xe8\xe9](....)", self.text, re.DOTALL):
            site = self.text_va + match.start()
            target = site + 5 + struct.unpack_from("<i", match.group(1))[0]
            if self.text_va <= target < text_end:
                (self.callers if match.group()[0] == 0xE8 else self.jumps)[
                    target
                ].append(site)
        self.calls_in = collections.defaultdict(set)
        for target, sites in self.callers.items():
            for site in sites:
                function = self.function_of(site)
                if function:
                    self.calls_in[function].add(target)
        self.string_users = collections.defaultdict(set)
        rva, raw = self.sections[".rdata"][1], self.sections[".rdata"][3]
        rdata_low, rdata_high = BASE + rva, BASE + rva + self.sections[".rdata"][0]
        for match in re.finditer(
            rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d](....)",
            self.text,
            re.DOTALL,
        ):
            site = self.text_va + match.start()
            target = site + 7 + struct.unpack_from("<i", match.group(1))[0]
            if rdata_low <= target < rdata_high:
                self.string_users[target].add(site)

    def function_of(self, address):
        index = bisect.bisect_right(self.starts, address) - 1
        return (
            self.starts[index]
            if index >= 0 and address < self.functions[index][1]
            else None
        )

    def size_of(self, function):
        return self.functions[bisect.bisect_left(self.starts, function)][1] - function

    def holding(self, text):
        """Functions that load this exact string."""
        _, rva, raw_size, raw = self.sections[".rdata"]
        needle = b"\0" + text.encode() + b"\0"
        found, position = set(), raw
        while (position := self.data.find(needle, position, raw + raw_size)) >= 0:
            for site in self.string_users.get(BASE + rva + position + 1 - raw, ()):
                function = self.function_of(site)
                if function:
                    found.add(function)
            position += 1
        return found

    def game_callers(self, target, game_end):
        return sum(site < game_end for site in self.callers.get(target, ()))

    def body(self, function):
        offset = function - self.text_va
        return self.text[offset : offset + self.size_of(function)]


def only(name, candidates):
    candidates = set(candidates)
    if len(candidates) != 1:
        sys.exit(
            f"helper `{name}`: expected one match, found {sorted(hex(c) for c in candidates)[:12]} ({len(candidates)})"
        )
    return candidates.pop()


def resolve(image, gml_functions):
    last_gml = max(gml_functions)
    game_end = last_gml + image.size_of(last_gml)
    found = {"game_end": game_end}
    size, rva, _, _ = image.sections[".data"]
    found["slot_lo"], found["slot_hi"] = BASE + rva, BASE + rva + size

    found["compare"] = only("compare", image.holding("Cannot compare unset variables"))
    found["to_real"] = only("to_real", image.holding("REAL argument is unset"))
    found["to_int"] = only("to_int", image.holding("I32 argument is undefined"))
    array_writers = image.holding(
        "Unable to write to immutable array"
    )  # the accessor and two rarely called relatives
    found["array_element"] = only(
        "array_element",
        (
            function
            for function in array_writers
            if image.game_callers(function, game_end) >= 1000
        ),
    )

    # array read `a[i]` with a constant index: `cmp eax,<length>; jl <error>; mov edx,<i>; call <array_get>` (the bounds check the runtime inlines); one target takes all of them
    reads = collections.Counter()
    for match in re.finditer(
        rb"\x83\xf8.\x0f\x8c....\xba....\xe8(....)", image.text, re.DOTALL
    ):
        reads[
            image.text_va
            + match.start()
            + 19
            + struct.unpack_from("<i", match.group(1))[0]
        ] += 1
    found["array_get"] = only(
        "array_get",
        (
            target
            for target, count in reads.items()
            if count >= 1000 and target >= game_end
        ),
    )

    # free / copy / init are the three most called functions in the game; init and copy both call free
    by_calls = sorted(
        image.callers,
        key=lambda target: image.game_callers(target, game_end),
        reverse=True,
    )
    free, rest = by_calls[0], by_calls[1:]
    pair = [target for target in rest[:2] if free in image.calls_in.get(target, ())]
    if len(pair) != 2:
        sys.exit(
            f"helper `free`/`rvalue_copy`/`rvalue_init`: the most called functions are {[hex(t) for t in by_calls[:3]]}, not free and its two callers"
        )
    found["free"] = [free]
    found["rvalue_init"], found["rvalue_copy"] = sorted(
        pair
    )  # both copy an RValue and differ only in the source; init comes first in the source file

    # arithmetic: `add` holds its error string; the others share add's one game-range callee (the string-or-number helper) and to_real
    add = max(
        image.holding("unable to add a number to string"),
        key=lambda function: image.game_callers(function, game_end),
    )  # `+=` and other relatives hold it too
    shared = only(
        "arith helper", (callee for callee in image.calls_in[add] if callee < game_end)
    )
    arith = {
        function
        for function in image.starts
        if function < game_end
        and {shared, found["to_real"]} <= image.calls_in.get(function, set())
        and image.game_callers(function, game_end) >= 300
    }
    if add not in arith or len(arith) != 3:
        sys.exit(
            f"helper `arith`: expected add and two others, found {sorted(hex(a) for a in arith)}"
        )
    found["arith"] = sorted(arith)

    # variable access: one compilation unit, laid out in source order around the setter that holds the read-only error (it anchors the getters)
    setter = only(
        "setter",
        image.holding(
            "Writing to variable '%s' in managed object '%s' which is read-only. %s"
        ),
    )
    family = sorted(
        target
        for target in image.callers
        if setter - 0x1000 <= target < setter + 0xC00
        and image.game_callers(target, game_end) >= 10
    )
    if len(family) != 12 or family[5] != setter:
        sys.exit(
            f"helper `variable access`: expected 12 functions with the setter sixth, found {[hex(f) for f in family]}"
        )
    get_slot, get_self, _, _, _, _, _, _, get_any, get_other, _, _ = family
    found["getters"] = [get_self, get_slot, get_other, get_any]

    return found


def main(exe_path, funcmap_path, out_path):
    image = Image(exe_path)
    gml_functions = {}
    for line in pathlib.Path(funcmap_path).read_text(encoding="utf-8").splitlines():
        va, name = line.split("\t")
        gml_functions[int(va, 16)] = name
    found = resolve(image, gml_functions)
    with pathlib.Path(out_path).open("w", encoding="utf-8", newline="\n") as out:
        out.write("{\n")
        rows = [
            f' "{name}": '
            + (
                json.dumps([f"{item:x}" for item in value])
                if isinstance(value, list)
                else json.dumps(f"{value:x}")
            )
            for name, value in found.items()
        ]
        out.write(",\n".join(rows) + "\n}\n")
    print(f"{len(found)} symbols")


if __name__ == "__main__":
    main(*sys.argv[1:4])
