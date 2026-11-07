"""Находит анонимные вспомогательные функции времени выполнения сборки YYC статически, только по exe: `python -I resolve_helpers.py <exe> <funcmap.tsv> <symbols.json>`

Ничего не сохраняется для каждой сборки. Каждая вспомогательная функция определяется по тому, чем она является: строке ошибки времени выполнения, которую она содержит, её месту среди того, что вызывают другие
вспомогательные функции, или тому, как часто её вызывает код игры. Каждое правило должно давать ровно ожидаемый результат, иначе запуск останавливается и называет
вспомогательную функцию: неверный адрес молча изменил бы отчёт о спрайтах. Если правило перестаёт работать после обновления среды выполнения GameMaker, правило нужно менять.

Вывод содержит один символ на строку — именно это разбирает Symbols.java."""
import bisect
import collections
import json
import re
import struct
import sys

BASE = 0x140000000


class Image:
    def __init__(self, path):
        self.data = data = open(path, "rb").read()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        count, optional = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
        self.sections = {}
        for index in range(count):
            header = pe + 24 + optional + 40 * index
            name = data[header:header + 8].rstrip(b"\0").decode()
            self.sections[name] = struct.unpack_from("<IIII", data, header + 8)  # virtual size, RVA, raw size, raw offset
        text_size, rva, raw_size, raw = self.sections[".text"]
        self.text, self.text_va = data[raw:raw + raw_size], BASE + rva
        _, rva, raw_size, raw = self.sections[".pdata"]
        ranges = {struct.unpack_from("<II", data, raw + at) for at in range(0, raw_size - 11, 12)}
        self.functions = sorted((BASE + begin, BASE + end) for begin, end in ranges if begin)
        self.starts = [begin for begin, _ in self.functions]
        # shortcut: linear byte scan, so a call-shaped byte run inside an instruction counts too; rules use exact strings or large counts, which it cannot sway
        self.callers = collections.defaultdict(list)
        self.jumps = collections.defaultdict(list)
        text_end = self.text_va + text_size
        for match in re.finditer(rb"[\xe8\xe9](....)", self.text, re.S):
            site = self.text_va + match.start()
            target = site + 5 + struct.unpack_from("<i", match.group(1))[0]
            if self.text_va <= target < text_end:
                (self.callers if match.group()[0] == 0xE8 else self.jumps)[target].append(site)
        self.calls_in = collections.defaultdict(set)
        for target, sites in self.callers.items():
            for site in sites:
                function = self.function_of(site)
                if function:
                    self.calls_in[function].add(target)
        self.string_users = collections.defaultdict(set)
        rva, raw = self.sections[".rdata"][1], self.sections[".rdata"][3]
        rdata_low, rdata_high = BASE + rva, BASE + rva + self.sections[".rdata"][0]
        for match in re.finditer(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d](....)", self.text, re.S):
            site = self.text_va + match.start()
            target = site + 7 + struct.unpack_from("<i", match.group(1))[0]
            if rdata_low <= target < rdata_high:
                self.string_users[target].add(site)

    def function_of(self, address):
        index = bisect.bisect_right(self.starts, address) - 1
        return self.starts[index] if index >= 0 and address < self.functions[index][1] else None

    def size_of(self, function):
        return self.functions[bisect.bisect_left(self.starts, function)][1] - function

    def holding(self, text):
        """Functions that load this exact string."""
        size, rva, raw_size, raw = self.sections[".rdata"]
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
        return self.text[offset:offset + self.size_of(function)]


def only(name, candidates):
    candidates = set(candidates)
    if len(candidates) != 1:
        sys.exit(f"helper `{name}`: expected one match, found {sorted(hex(c) for c in candidates)[:12]} ({len(candidates)})")
    return candidates.pop()


def resolve(image, gml_functions):
    last_gml = max(gml_functions)
    game_end = last_gml + image.size_of(last_gml)
    runtime = [function for function in image.starts if function >= game_end]
    found = {"game_end": game_end}
    size, rva, _, _ = image.sections[".data"]
    found["slot_lo"], found["slot_hi"] = BASE + rva, BASE + rva + size

    found["compare"] = only("compare", image.holding("Cannot compare unset variables"))
    found["to_real"] = only("to_real", image.holding("REAL argument is unset"))
    found["to_int"] = only("to_int", image.holding("I32 argument is undefined"))
    array_writers = image.holding("Unable to write to immutable array")  # the accessor and two rarely called relatives
    found["array_element"] = only("array_element", (function for function in array_writers if image.game_callers(function, game_end) >= 1000))

    # free / copy / init are the three most called functions in the game; init and copy both call free
    by_calls = sorted(image.callers, key=lambda target: image.game_callers(target, game_end), reverse=True)
    free, rest = by_calls[0], by_calls[1:]
    pair = [target for target in rest[:2] if free in image.calls_in.get(target, ())]
    if len(pair) != 2:
        sys.exit(f"helper `free`/`rvalue_copy`/`rvalue_init`: the most called functions are {[hex(t) for t in by_calls[:3]]}, not free and its two callers")
    found["free"] = [free]
    found["rvalue_init"], found["rvalue_copy"] = sorted(pair)  # both copy an RValue and differ only in the source; init comes first in the source file

    # arithmetic: `add` holds its error string; the others share add's one game-range callee (the string-or-number helper) and to_real
    add = max(image.holding("unable to add a number to string"), key=lambda function: image.game_callers(function, game_end))  # `+=` and other relatives hold it too
    shared = only("arith helper", (callee for callee in image.calls_in[add] if callee < game_end))
    arith = {function for function in image.starts
             if function < game_end and {shared, found["to_real"]} <= image.calls_in.get(function, set()) and image.game_callers(function, game_end) >= 300}
    if add not in arith or len(arith) != 3:
        sys.exit(f"helper `arith`: expected add and two others, found {sorted(hex(a) for a in arith)}")
    found["arith"] = sorted(arith)

    # the small game-range wrappers: around the arith helper that never converts to int, and compare-with-int (cvtsi2sd xmm0,edx, then compare)
    real_only = only("real-only arith", (function for function in arith if found["to_int"] not in image.calls_in[function]))
    wrappers = {function for function in image.starts if function < game_end and function not in gml_functions and image.size_of(function) <= 140
                and {free, real_only} <= image.calls_in.get(function, set()) and image.game_callers(function, game_end) >= 300}
    compare_int = [function for function in image.starts if function < game_end and function not in gml_functions and image.size_of(function) <= 140
                   and b"\xf2\x0f\x2a\xc2" in image.body(function) and image.game_callers(function, game_end) >= 300]
    found["tierc_arith"] = sorted({only("tierc wrapper", wrappers), only("compare_int", compare_int)})

    # sprite natives: everything that draws a sprite fetches it through the one callee the registered draw built-ins share
    fetch_users = image.holding("Trying to draw non-existing sprite.")
    draw_self = only("draw_self", (function for function in fetch_users if image.game_callers(function, game_end) > 0))
    candidates = [callee for callee in image.calls_in[draw_self] if callee >= game_end]
    fetch = max(candidates, key=lambda callee: len(image.callers[callee]))
    natives = {function for function in runtime if fetch in image.calls_in.get(function, ()) and image.game_callers(function, game_end) > 0} - {draw_self}
    ordered = sorted(natives, key=lambda function: image.game_callers(function, game_end), reverse=True)
    if len(ordered) != 3:
        sys.exit(f"helper `draw natives`: expected 3, found {[hex(n) for n in ordered]}")
    found["draw_sprite"], found["draw_sprite_ext"], found["draw_sprite_part"] = ordered
    found["draw_self"] = draw_self

    # variable access: one compilation unit, laid out in source order around the setter that holds the read-only error
    setter = only("setter", image.holding("Writing to variable '%s' in managed object '%s' which is read-only. %s"))
    family = sorted(target for target in image.callers if setter - 0x1000 <= target < setter + 0xC00 and image.game_callers(target, game_end) >= 10)
    if len(family) != 12 or family[5] != setter:
        sys.exit(f"helper `variable access`: expected 12 functions with the setter sixth, found {[hex(f) for f in family]}")
    get_slot, get_self, set_slot, op_any, op_self, _, op_other, _, get_any, get_other, set_any, set_other = family
    found["getters"] = [get_self, get_slot, get_other, get_any]
    found["setters"] = [setter, set_other, set_slot]  # set_any converts its target and tail-jumps to set_other, so only Flow.java sees it (setters_flow)
    found["setters_flow"] = [setter, set_other, set_slot, set_any]
    found["op_setters"] = [op_any, op_self, op_other]

    created = [function for function, name in gml_functions.items() if name in ("gml_Script_instance_create", "gml_GlobalScript_instance_create")]
    if len(created) != 2:
        sys.exit(f"helper `create_wrappers`: found {[hex(c) for c in created]}")
    found["create_wrappers"] = sorted(created)
    return found


def main(exe_path, funcmap_path, out_path):
    image = Image(exe_path)
    gml_functions = {}
    for line in open(funcmap_path, encoding="utf-8"):
        va, name = line.rstrip("\n").split("\t")
        gml_functions[int(va, 16)] = name
    found = resolve(image, gml_functions)
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        out.write("{\n")
        rows = [f' "{name}": ' + (json.dumps([f"{item:x}" for item in value]) if isinstance(value, list) else json.dumps(f"{value:x}"))
                for name, value in found.items()]
        out.write(",\n".join(rows) + "\n}\n")
    print(f"{len(found)} symbols")


if __name__ == "__main__":
    main(*sys.argv[1:4])
