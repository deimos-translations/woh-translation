"""Classify the strings of targets.tsv by what the code does with them.

Usage: python -I pipeline/generate/classify_usage.py <targets.tsv> <uses.tsv> <compare function VA, hex> <usage.tsv>

uses.tsv is the `.uses.tsv` output of StringUses.java. The compare function is the one that holds the string "Cannot compare unset
variables" (resolve_helpers.py finds it). A text is `logic` when the value is passed to the compare function within the first six
calls after it is loaded, i.e. the code tests it against something (`if (x == "PREP")`). `logic` means a translation must stay
consistent with every other place that produces or tests the value. The other class, `not-compared-nearby`, is not a proof of safety:
the value can be stored and tested in a different script.
"""
import collections
import re
import sys

UNESCAPES = {"\\\\": "\\", "\\r": "\r", "\\n": "\n", "\\t": "\t"}


def unescape(text):
    return re.sub(r"\\[\\rnt]", lambda match: UNESCAPES[match.group()], text)


def main(targets_path, uses_path, compare_va, usage_path):
    texts = {}
    for line in open(targets_path, encoding="utf-8", newline=""):
        va, text = line.rstrip("\n").split("\t")
        texts[va] = unescape(text)
    stats = collections.OrderedDict((text, {"copies": 0, "uses": 0, "compares": 0, "scripts": set()}) for text in texts.values())
    for text in texts.values():
        stats[text]["copies"] += 1
    for line in open(uses_path, encoding="utf-8"):
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 6 or cols[0] not in texts:
            continue
        stat = stats[texts[cols[0]]]
        stat["uses"] += 1
        if compare_va in [call for call in cols[5].split(",") if call][:6]:
            stat["compares"] += 1
        stat["scripts"].add(cols[4] or "?")
    with open(usage_path, "w", encoding="utf-8", newline="") as out:
        out.write("class\tcopies\tuses\tcompares\tscripts\ttext\n")
        for text, stat in stats.items():
            kind = "logic" if stat["compares"] else "not-compared-nearby" if stat["uses"] else "no-use-found"
            scripts = ",".join(sorted(stat["scripts"]))[:100]
            out.write(f"{kind}\t{stat['copies']}\t{stat['uses']}\t{stat['compares']}\t{scripts}\t{text!a}\n")
    counts = collections.Counter("logic" if s["compares"] else "not-compared-nearby" if s["uses"] else "no-use-found"
                                 for s in stats.values())
    print(dict(counts))


if __name__ == "__main__":
    main(*sys.argv[1:5])
