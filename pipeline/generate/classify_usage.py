"""Classifies the targets.tsv strings by what the code does with them.

Usage: python -I pipeline/generate/classify_usage.py <targets.tsv> <uses.tsv> <compare function VA, hex> <usage.tsv> [strflow.tsv] [slots.tsv] [exe]

uses.tsv is the `.uses.tsv` output of StringUses.java. The compare function is the one containing the string "Cannot compare unset
variables" (resolve_helpers.py finds it). A text is `logic` when its value is passed to the compare function within the first six
calls after loading, i.e. the code tests it against something (`if (x == "PREP")`). The other class, `not-compared-nearby`, does not prove safety:
the value may be stored and checked in another script.
With strflow.tsv (the `V` lines of Flow.java in strings mode: a comparison where one operand is a known number and there are no strings) comparisons with a number in the window do not count (`rolled` is loaded before the `language == 1…` checks but not compared).
With slots.tsv (allslots.py) a text is also `logic` when a variable name ends in `_<text>`: the code builds the name by concatenation
(`variable_global_set("status_" + name, …)` for `fearful`), and a substituted copy would leave `status_fearful` unset.
With the exe a text is also `logic` when the code copies its slot into a static cell (`mov rax,[slot]; mov [static],rax`): YYC builds
the `case` value table of a string `switch` that way (`draw_script_event_location`), and the comparison happens later through the table.
"""

import collections
import pathlib
import re
import struct
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent)
)  # -I does not add the script directory
import common

STATIC_COPY = re.compile(
    rb"\x48\x8b\x05(.{4})\x48\x89\x05", re.DOTALL
)  # mov rax,[rip+d]; mov [rip+d2],rax


def static_copied_slots(exe_path):
    """VAs that code copies straight into a static cell: the source of every `mov rax,[rip+d]; mov [rip+d2],rax` in .text."""
    data = pathlib.Path(exe_path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    image_base = struct.unpack_from("<Q", data, pe + 24 + 24)[0]
    section = common.pe_sections(data).get(".text")
    if section is None:
        raise SystemExit(f"{exe_path}: no .text section")
    _vsize, rva, raw_size, raw = section
    base = image_base + rva + 7  # VA of the end of a match at offset 0 of .text
    text = memoryview(data)[raw : raw + raw_size]
    return {
        base + match.start() + struct.unpack("<i", match.group(1))[0]
        for match in STATIC_COPY.finditer(text)
    }


def classify(stat):
    return (
        "logic"
        if stat["compares"] or stat.get("keyed")
        else "not-compared-nearby"
        if stat["uses"]
        else "no-use-found"
    )


def main(
    targets_path,
    uses_path,
    compare_va,
    usage_path,
    flow_path=None,
    slots_path=None,
    exe_path=None,
):
    numeric = collections.defaultdict(
        list
    )  # function -> sites of compares with a known number
    if flow_path:
        with pathlib.Path(flow_path).open(encoding="utf-8") as file:
            for line in file:
                if line.startswith("V\t"):
                    _kind, function, site, is_numeric = line.rstrip("\n").split("\t")[
                        :4
                    ]
                    numeric[function].append((int(site, 16), is_numeric == "1"))
    for sites in numeric.values():
        sites.sort()
    texts = {}
    with pathlib.Path(targets_path).open(encoding="utf-8", newline="") as file:
        for line in file:
            va, text = line.rstrip("\n").split("\t")
            texts[va] = common.unescape(text)
    stats = collections.OrderedDict(
        (text, {"copies": 0, "uses": 0, "compares": 0, "scripts": set()})
        for text in texts.values()
    )
    copied = static_copied_slots(exe_path) if exe_path else set()
    for text in texts.values():
        stats[text]["copies"] += 1
    with pathlib.Path(uses_path).open(encoding="utf-8") as file:
        for line in file:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 6 or cols[0] not in texts:
                continue
            stat = stats[texts[cols[0]]]
            stat["uses"] += 1
            if int(cols[1], 16) in copied:
                stat["keyed"] = (
                    True  # a `switch` case value: compared later through the static table
                )
            compares = [call for call in cols[5].split(",") if call][:6].count(
                compare_va
            )
            if compares:
                site = int(cols[2], 16)
                following = [
                    is_numeric
                    for at, is_numeric in numeric.get(cols[3], ())
                    if at >= site
                ][:compares]  # the compare calls the window counted, in order
                compares -= sum(following)
            if compares > 0:
                stat["compares"] += 1
            stat["scripts"].add(cols[4] or "?")
    if slots_path:
        with pathlib.Path(slots_path).open(encoding="utf-8") as file:
            names = [line.rstrip("\n").split("\t")[1] for line in file]
        suffixes = {
            name[at:] for name in names for at, char in enumerate(name) if char == "_"
        }  # every `_tail` of every name
        for text, stat in stats.items():
            if text and "_" + text in suffixes:
                stat["keyed"] = (
                    True  # the name-building concatenation acts as the comparison
                )
    with pathlib.Path(usage_path).open("w", encoding="utf-8", newline="") as out:
        out.write("class\tcopies\tuses\tcompares\tscripts\ttext\n")
        for text, stat in stats.items():
            scripts = ",".join(sorted(stat["scripts"]))[:100]
            out.write(
                f"{classify(stat)}\t{stat['copies']}\t{stat['uses']}\t{stat['compares']}\t{scripts}\t{text!a}\n"
            )
    print(dict(collections.Counter(classify(stat) for stat in stats.values())))


if __name__ == "__main__":
    main(*sys.argv[1:8])
