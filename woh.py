# /// script
# dependencies = ["pillow"]
# ///
"""Конвейер перевода World of Horror: обратная инженерия установленной сборки, создание артефактов, выполнение действий.

    uv run woh.py [--game DIR] [--force STAGE,STAGE] <команда> [аргументы]

Команды (каждая запускает всё, что ей нужно и что ещё не собрано):
    build [--no-exe] [--no-text] [--no-sprites] [--no-hashes] [--literal]
                            полная сборка в output/: language/engLanguage/*.jn, data.win, worldofhorror.exe; hashes.txt; каждый --no-* пропускает эту часть
                            (--literal: также перенаправить собственные копии текстов exe, которые код не сравнивает)
    sync                   обновить отслеживаемые документы перевода из игры (единственная команда, которая пишет в отслеживаемые файлы)
    report                 какие спрайты и кадры используются, и translation_audit.tsv
    extract                каждый кадр спрайта в img/source/, шрифты в кэш
    ocr                    текст, найденный в извлечённых кадрах
    save [IN] OUT          сохранение со всеми разблокировками
    check                  тест размеров, а также нативные тесты хука в Windows
    list                   все этапы по группам: re (обратная инженерия), gen (артефакты), act (действия)

Файлы игры по умолчанию берутся из установки Steam; --game DIR нужен для другой библиотеки Steam. Всё, что из них производится, хранится в
build/<exe md5:8>-<data md5:8>/, поэтому артефакты всегда относятся к установленной сборке. Этапы, чьи выходные данные уже есть, пропускаются.
Инструменты берутся из окружения: GHIDRA_HEADLESS (analyzeHeadless), WOH_GHIDRA_JAVA (JAVA_HOME для Ghidra), UTMT_CLI (UndertaleModCli).
Clang и uv берутся из PATH.
"""
import argparse
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
PIPELINE = ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "reverse"))
import common

REVERSE, GENERATE, ACT, CHECK = (PIPELINE / name for name in ("reverse", "generate", "act", "check"))
OUT = "out/sprites"
MIN_SPRITE_ID = 12  # smaller constants collide with plain numbers and are not tracked by the consumer scans
DEBUG_VARIABLES = ["debug", "god_debug"]  # assumed false; resolved to slot addresses by name from the exe
SPRITE_INDEX_VARIABLE = "sprite_index"
DEBUG_ID_KINDS = {"nenm": "enemy", "evt": "event", "itm": "item", "upg": "perk", "stat": "status", "spl": "spell", "fol": "ally"}  # in output order
SAVE_DECOMPILE_TIMEOUT = "1800"
# The B of the "A/B" small-card label: the 22x22 box at (30, 162) of img/source/s_smallcard_24.png, '#' black, '.' white.
SMALLCARD_X, SMALLCARD_Y, SMALLCARD_SIZE = 30, 162, 22
SMALLCARD_BOX = (
    "#....................#",
    "...................##.",
    "...###............###.",
    "...###...........###..",
    "..##.##.........###...",
    "..##.##........###....",
    "..#####.......###.....",
    ".##...##.....###......",
    ".##...##....###.......",
    "...........###........",
    "..........###.........",
    ".........###..........",
    "........###...........",
    ".......###....######..",
    "......###.....##...##.",
    ".....###......##...##.",
    "....###.......######..",
    "...###........##...##.",
    "..###.........##...##.",
    ".###..........######..",
    ".##...................",
    "#....................#",
)
SMALLCARD_RECOLOR = ((19, 14), (20, 15), (20, 14), (19, 15))  # (x, y) inside the box: black becomes white
_BLACK, _WHITE = (0, 0, 0, 255), (255, 255, 255, 255)
SMALLCARD_ORIGINAL = bytes(channel for row in SMALLCARD_BOX for cell in row for channel in (_BLACK if cell == "#" else _WHITE))

STAGES = {}  # name -> (group, outputs, needs, function), in definition order
done = set()
forced = set()
game = None  # the game folder
literal = False
skipped = set()  # build parts left out by --no-exe, --no-text, --no-sprites
command_args = []


def stage(name, group, *outputs, needs=()):
    def decorate(function):
        STAGES[name] = (group, outputs, needs, function)
        return function
    return decorate


def say(message):
    print(message, flush=True)


def build(name):
    """Run a stage after what it needs. shortcut: a stage is current when its outputs exist, editing a script does not invalidate them; use --force."""
    if name in done:
        return
    done.add(name)
    _group, outputs, needs, function = STAGES[name]
    for need in needs:
        build(need)
    if outputs and name not in forced and all(os.path.exists(path) and os.path.getsize(path) > 0 for path in outputs):
        say(f"[{name}] current")
        return
    started = time.time()
    say(f"[{name}] ...")
    try:
        function()
    except BaseException:
        for path in outputs:  # a partial output must not pass as finished on the next run
            if os.path.exists(path):
                os.remove(path)
        raise
    missing = [path for path in outputs if not os.path.exists(path)]
    if missing:
        sys.exit(f"stage {name} did not write {', '.join(missing)}")
    say(f"[{name}] done in {time.time() - started:.0f}s")


def run_python(script, *args, stdout=None):
    command = [sys.executable, "-I", str(script), *map(str, args)]
    log_path = pathlib.Path("out/logs", pathlib.Path(script).name + ".log")
    with open(log_path, "w", encoding="utf-8") as log, (open(stdout, "w", encoding="utf-8", newline="\n") if stdout else log) as target:
        result = subprocess.run(command, stdout=target, stderr=log if stdout else subprocess.STDOUT, text=True, check=False)
    if result.returncode:
        sys.exit(f"failed: {' '.join(command)} (see {log_path.resolve()})")


def run_shown(*command, env=None):
    """An action: its output is what the user came for."""
    subprocess.run([str(part) for part in command], check=True, env=env)


def ghidra_env():
    env = dict(os.environ, GHIDRA_HEADLESS_MAXMEM="6G", MSYS_NO_PATHCONV="1")  # the 2 GB default runs out of memory
    if os.environ.get("WOH_GHIDRA_JAVA"):
        env["JAVA_HOME"] = os.environ["WOH_GHIDRA_JAVA"]
    if "GHIDRA_HEADLESS" not in os.environ and not shutil.which("analyzeHeadless"):
        sys.exit("analyzeHeadless not found: set GHIDRA_HEADLESS")
    return env


def ghidra_command(*args):
    return [os.environ.get("GHIDRA_HEADLESS", "analyzeHeadless"), str(pathlib.Path("ghidra").resolve()), "woh", *args]


def run_ghidra_logged(log_name, command):
    log_path = pathlib.Path("out/logs", log_name + ".log")
    with open(log_path, "w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=ghidra_env(), check=False)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if result.returncode or " error:" in text or "SCRIPT ERROR" in text or "The class could not be found" in text or "OutOfMemoryError" in text:
        sys.exit(f"Ghidra {log_name} failed (see {log_path.resolve()})")
    return text


def run_ghidra(script, *args):
    env_args = [os.path.abspath(arg) if str(arg).startswith("out/") else str(arg) for arg in args]  # analyzeHeadless may change directory
    os.environ["WOH_SYMBOLS"] = os.path.abspath("out/symbols.json")
    run_ghidra_logged(script, ghidra_command("-process", common.EXE, "-noanalysis", "-readOnly", "-scriptPath", str(REVERSE),
                                             "-postScript", script, *env_args))


def symbols():
    return json.load(open("out/symbols.json"))


def rows(path):
    return [line.rstrip("\n").split("\t") for line in open(path, encoding="utf-8")]


def data_win_counts():
    with open(game / common.DATA_WIN, "rb") as file:
        data = file.read()
    return struct.unpack_from("<I", data, common.data_win_chunks(data)["SPRT"])[0]


# ---------------------------------------------------------------- step 1: reverse engineering

@stage("ghidra-import", "re", "ghidra/imported.ok")
def ghidra_import():
    # a copy in the cache: analyzeHeadless.bat breaks on the `(x86)` and spaces of the Steam path
    os.makedirs("ghidra", exist_ok=True)
    copy = pathlib.Path("ghidra-input", common.EXE)
    copy.parent.mkdir(exist_ok=True)
    shutil.copyfile(game / common.EXE, copy)
    try:
        text = run_ghidra_logged("ghidra-import", ghidra_command("-import", str(copy.resolve()), "-overwrite", "-scriptPath", str(REVERSE),
                                                                 "-preScript", "FastAnalysis.java"))
    finally:
        shutil.rmtree(copy.parent)
    if "Save succeeded" not in text:  # an exited process is not enough
        sys.exit("Ghidra import did not save the project (see out/logs/ghidra-import.log)")
    common.record_hashes(".exe", [(common.sha256(game / common.EXE), common.EXE)])  # the exe this disassembly is of
    pathlib.Path("ghidra/imported.ok").write_text("ok\n")


@stage("patch-sites", "re", "out/patch_sites.tsv", needs=("ghidra-import",))
def patch_sites():
    run_ghidra("FindPatchSites.java", "out/patch_sites.tsv")


@stage("draw-hooks", "re", "out/draw_hooks.tsv", needs=("ghidra-import",))
def draw_hooks():
    run_ghidra("FindDrawHooks.java", "out/draw_hooks.tsv")


@stage("pool-strings", "re", "out/pool_strings.tsv", needs=("ghidra-import",))
def pool_strings():
    import slotstrings
    literals = slotstrings.load(str(game / common.EXE), literal_addresses=True)
    start, end = min(literals), max(literals) + 1
    run_ghidra("ExportPoolStrings.java", f"{start:x}", str(end - start), "out/pool_strings.tsv")


@stage("string-refs", "re", "out/refs.tsv", needs=("targets",))
def string_refs():
    run_ghidra("ExportStringRefs.java", "out/targets.tsv", "out/refs.tsv")


@stage("string-uses", "re", "out/uses.uses.tsv", needs=("targets",))
def string_uses():
    run_ghidra("StringUses.java", "out/targets.tsv", "out/uses")


@stage("slots", "re", OUT + "/slots.tsv")
def slots():
    run_python(REVERSE / "allslots.py", game / common.EXE, stdout=OUT + "/slots.tsv")


@stage("funcmap", "re", OUT + "/funcmap.tsv")
def funcmap():
    run_python(REVERSE / "funcmap.py", game / common.EXE, OUT + "/funcmap.tsv")


@stage("objects", "re", "out/objects.tsv")
def objects():
    run_python(REVERSE / "objects.py", game / common.DATA_WIN, "out/objects.tsv")


@stage("helpers", "re", "out/symbols.json", needs=("funcmap",))
def helpers():
    run_python(REVERSE / "resolve_helpers.py", game / common.EXE, OUT + "/funcmap.tsv", "out/symbols.json")


def scan(name, script, *outputs, args=lambda: ()):
    @stage(name, "re", *outputs, needs=("ghidra-import", "helpers"))
    def run():
        run_ghidra(script, *outputs, *args())


def sprite_count_args():
    return str(data_win_counts()), str(MIN_SPRITE_ID)


def draw_sinks():
    known = symbols()
    return [known["draw_sprite"], known["draw_sprite_ext"], known["draw_sprite_part"]]


scan("scan-sites", "SpriteRefs.java", OUT + "/sites.tsv", OUT + "/consts.tsv",
     args=lambda: [str(data_win_counts()), *draw_sinks(), symbols()["draw_self"]])
scan("scan-consumers", "Consumers.java", OUT + "/consumers.tsv", args=sprite_count_args)
scan("scan-setsites", "SetSites.java", OUT + "/setsites.tsv")
scan("scan-lval", "LvalStores.java", OUT + "/lval.tsv")
scan("scan-elem", "ElemStores.java", OUT + "/elem.tsv", args=sprite_count_args)
scan("scan-bcalls", "BuiltinCalls.java", OUT + "/bcalls.tsv")
scan("scan-scriptcalls", "BuiltinCalls.java", OUT + "/scriptcalls.tsv", args=lambda: symbols()["create_wrappers"])


@stage("config", "gen", "out/sprite_config.json", needs=("slots", "helpers"))
def config():
    wanted = {*DEBUG_VARIABLES, SPRITE_INDEX_VARIABLE}
    found = {}
    for address, name in rows(OUT + "/slots.tsv"):
        if name in wanted:
            found.setdefault(name, []).append(address)
    for name in wanted:
        if len(found.get(name, [])) != 1:
            sys.exit(f"variable `{name}` must have exactly one slot in the exe, found {found.get(name)}")
    known = symbols()
    with open("out/sprite_config.json", "w") as out:
        json.dump({"sprite_index": found[SPRITE_INDEX_VARIABLE][0], "debug_slots": [found[name][0] for name in DEBUG_VARIABLES],
                   "draw_self": known["draw_self"], "draw_sinks": draw_sinks(), "create_wrappers": known["create_wrappers"]}, out, indent=1)


@stage("scan-flow", "re", OUT + "/flow.tsv", needs=("ghidra-import", "config"))
def scan_flow():
    with open("out/sprite_config.json") as file:
        debug_slots = json.load(file)["debug_slots"]
    run_ghidra("Flow.java", OUT + "/flow.tsv", *debug_slots)


@stage("decomp-save", "re", "out/decomp/save.ok", needs=("ghidra-import", "funcmap"))
def decomp_save():
    addresses = [address for address, name in rows(OUT + "/funcmap.tsv") if name == "gml_Script_endgame_check_achievements"]
    if len(addresses) != 1:
        sys.exit(f"gml_Script_endgame_check_achievements: found {addresses}")
    run_ghidra("DecompBig.java", "out/decomp", SAVE_DECOMPILE_TIMEOUT, addresses[0])
    pathlib.Path("out/decomp/save.ok").write_text(addresses[0] + "\n")


# ---------------------------------------------------------------- step 2: artifacts

@stage("hook", "gen", "out/hook.bin", "out/hook.json")
def hook():
    run_python(GENERATE / "hook" / "build.py", "out")


@stage("targets", "gen", "out/targets.tsv", needs=("pool-strings", "patch-sites"))
def targets():
    run_python(GENERATE / "make_targets.py", "out/pool_strings.tsv", common.TRANSLATION / "exe_strings.txt", "out/patch_sites.tsv", "out/targets.tsv")


@stage("usage", "gen", "out/usage.tsv", needs=("string-uses", "helpers"))
def usage():
    run_python(GENERATE / "classify_usage.py", "out/targets.tsv", "out/uses.uses.tsv", symbols()["compare"], "out/usage.tsv")


@stage("debug-ids", "gen", "out/debug_ids.tsv", needs=("objects",))
def debug_ids():
    """The numpad spawn console's typed IDs: `<prefix>_<NNN>_<name>` objects (see pipeline/README.md, "Debug features")."""
    order = list(DEBUG_ID_KINDS)
    found = []
    for row in rows("out/objects.tsv")[1:]:
        prefix, _, rest = row[1].partition("_")
        number = rest.partition("_")[0]
        if prefix in DEBUG_ID_KINDS and number.isdigit():
            found.append((order.index(prefix), number, row[1]))
    with open("out/debug_ids.tsv", "w", encoding="utf-8", newline="\n") as out:
        out.write("kind\tid\tasset\n")
        out.writelines(f"{DEBUG_ID_KINDS[order[kind]]}\t{number}\t{asset}\n" for kind, number, asset in sorted(found))


@stage("save-codes", "gen", "out/save_codes.json", needs=("decomp-save",))
def save_codes():
    decompiled = [str(path) for path in pathlib.Path("out/decomp").glob("*.c") if not path.name.endswith(".named.c")]
    run_python(REVERSE / "slotnames.py", game / common.EXE, *decompiled)
    run_python(GENERATE / "achiev_codes.py", decompiled[0][:-2] + ".named.c", "out/save_codes.json")


@stage("save-keys", "gen", "out/save_keys.json", needs=("funcmap",))
def save_keys():
    addresses = [address for address, name in rows(OUT + "/funcmap.tsv") if name == "gml_Script_scr_systemsave"]
    if len(addresses) != 1:
        sys.exit(f"gml_Script_scr_systemsave: found {addresses}")
    run_python(REVERSE / "inicalls.py", game / common.EXE, addresses[0], stdout="out/ini_calls.txt")
    run_python(GENERATE / "save_keys.py", game / common.EXE, OUT + "/funcmap.tsv", "out/ini_calls.txt", "out/save_keys.json")


@stage("sprite-usage", "gen", "out/sprite_usage.tsv", needs=("scan-sites",))
def sprite_usage():
    run_python(GENERATE / "sprite_usage.py", game / common.DATA_WIN, OUT + "/sites.tsv", OUT + "/consts.tsv", "out/sprite_usage.tsv", *draw_sinks())


@stage("tierc", "gen", "out/sprite_tierc.tsv", needs=("sprite-usage", "scan-consumers", "slots"))
def tierc():
    run_python(GENERATE / "tierc_filter.py", "out/sprite_usage.tsv", OUT + "/consumers.tsv", OUT + "/slots.tsv", "out/sprite_tierc.tsv")


@stage("sprite-vars", "gen", "out/sprite_varassign.tsv", needs=("sprite-usage", "scan-lval", "scan-setsites", "scan-elem", "slots"))
def sprite_vars():
    run_python(GENERATE / "sprite_vars.py", "out/sprite_usage.tsv", OUT + "/slots.tsv", OUT + "/lval.tsv", OUT + "/setsites.tsv", OUT + "/elem.tsv",
               "out/sprite_varassign.tsv")


@stage("flow-solve", "gen", "out/sprite_flow.tsv", needs=("scan-flow", "sprite-usage", "slots"))
def flow_solve():
    run_python(GENERATE / "flow_solve.py", OUT + "/flow.tsv", OUT + "/slots.tsv", "out/sprite_usage.tsv", "out/sprite_flow.tsv")


@stage("coord-only", "gen", "out/sprite_coordonly.tsv", needs=("scan-flow", "scan-elem", "sprite-usage", "slots"))
def coord_only():
    run_python(GENERATE / "coord_only.py")


@stage("reach", "gen", "out/sprite_reach.tsv", "out/objects_alive.tsv", "out/func_reach.tsv",
       needs=("objects", "funcmap", "slots", "config", "scan-flow", "scan-bcalls", "scan-scriptcalls", "sprite-usage"))
def reach():
    run_python(GENERATE / "reach.py")


@stage("final", "gen", "out/sprite_final.tsv", needs=("reach", "tierc", "sprite-vars", "flow-solve", "coord-only", "scan-sites"))
def final():
    run_python(GENERATE / "sprite_final.py")


@stage("frames", "gen", "out/sprite_frames.tsv", needs=("final", "reach", "sprite-vars", "flow-solve", "scan-bcalls"))
def frames():
    run_python(GENERATE / "frames.py", game / common.DATA_WIN)


@stage("sprite-report", "gen", "out/sprite_report.md", "out/sprite_report.tsv", "out/sprite_frame_report.tsv", needs=("final", "frames"))
def sprite_report():
    run_python(GENERATE / "report.py", game / common.DATA_WIN)


@stage("audit", "gen", "out/translation_audit.tsv", needs=("sprite-report",))
def audit():
    run_python(GENERATE / "audit_files.py")


def utmt():
    tool = os.environ.get("UTMT_CLI") or shutil.which("UndertaleModCli")
    if not tool:
        sys.exit("UndertaleModCli not found: set UTMT_CLI")
    return tool


@stage("extract-frames", "gen", "out/extract/sprites_manifest.tsv")
def extract_frames():
    frames_dir = ROOT / "img" / "source"
    shutil.rmtree(frames_dir, ignore_errors=True)  # img/source only ever holds one build's frames
    frames_dir.mkdir(parents=True)
    os.makedirs("out/extract/fonts", exist_ok=True)
    env = dict(os.environ, WOH_OUT=os.path.abspath("out/extract"), WOH_SPRITES=str(frames_dir))
    subprocess.run([utmt(), "load", str(game / common.DATA_WIN), "-s", str(GENERATE / "export_woh.csx")], env=env, check=True, stdout=sys.stderr)


@stage("ocr-text", "gen", "out/ocr_text.txt", needs=("extract-frames",))
def ocr_text():
    run_shown("uv", "run", ACT / "ocr_sprites.py", "--out", os.path.abspath("out/ocr_text.txt"))


# ---------------------------------------------------------------- step 3: actions (always run: they also depend on the authored files)

@stage("exe", "act", needs=("patch-sites", "draw-hooks", "hook"))
def exe():
    command = [sys.executable, "-I", ACT / "patch.py", "--game", game]
    if literal:
        build("string-refs")
        build("usage")
        command.append("--literal")
    run_shown(*command)


@stage("text", "act")
def text():
    run_shown(sys.executable, "-I", ACT / "woh_txt.py", "apply", "--source", game / common.LANGUAGE)


@stage("sprites", "act", needs=("sprite-images",))
def sprites():
    run_shown(sys.executable, "-I", ACT / "replace_sprites.py", "--images", os.path.abspath(os.path.join(OUT, "images")), "--data", game / common.DATA_WIN, "--utmt", utmt())


@stage("hashes", "act", needs=("extract-frames",))
def source_hashes():
    """sha256 of each extracted frame in img/source that has a PNG of the same name in img/translation: the game's original pixels, tracked in hashes.txt."""
    source = ROOT / "img" / "source"
    wanted = sorted(path.name for path in (ROOT / "img" / "translation").glob("*.png"))
    missing = [name for name in wanted if not (source / name).is_file()]
    if missing:
        sys.exit(f"not in img/source: {', '.join(missing)}")
    common.record_hashes(".png", [(common.sha256(source / name), name) for name in wanted])
    say(f"hashes.txt: {len(wanted)} sprites")


@stage("build", "act")
def build_output():
    for part in ("exe", "text", "sprites", "hashes"):
        if part not in skipped:
            build(part)
    say(f"output: {common.OUTPUT}")


@stage("sync", "act", needs=("targets",))
def sync():
    run_shown(sys.executable, "-I", ACT / "woh_txt.py", "carry", "--source", game / common.LANGUAGE)
    run_shown(sys.executable, "-I", ACT / "exe_strings.py", "out/targets.tsv")


@stage("report", "act", needs=("audit", "debug-ids"))
def report():
    with open("out/sprite_report.md", encoding="utf-8") as file:
        say("".join(file.readlines()[4:11]))
    say(f"reports: {CACHE / 'out'}")


@stage("extract", "act", needs=("extract-frames",))
def extract():
    say(f"frames: {ROOT / 'img' / 'source'}; fonts: {CACHE / 'out' / 'extract'}")


@stage("ocr", "act", needs=("ocr-text",))
def ocr():
    say(f"OCR text: {CACHE / 'out' / 'ocr_text.txt'}")


def smallcard_recoloured(path):
    """The image at path as RGBA with the small-card B recoloured, or None when its box is not the original."""
    from PIL import Image  # Pillow, declared in the script header

    box = (SMALLCARD_X, SMALLCARD_Y, SMALLCARD_X + SMALLCARD_SIZE, SMALLCARD_Y + SMALLCARD_SIZE)
    with Image.open(path) as image:
        if image.crop(box).convert("RGBA").tobytes() != SMALLCARD_ORIGINAL:
            return None
        rgba = image.convert("RGBA")
    for x, y in SMALLCARD_RECOLOR:
        rgba.putpixel((SMALLCARD_X + x, SMALLCARD_Y + y), _WHITE)
    return rgba


def psd_to_png(source, destination):
    """Dump the PSD's composite, the flattened picture Photoshop stores with the file, as RGBA PNG."""
    from PIL import Image  # Pillow, declared in the script header

    with Image.open(source) as psd:
        psd.convert("RGBA").save(destination)


@stage("sprite-images", "act", needs=("extract-frames",))
def sprite_images():
    """The PNGs that sprites writes into data.win, in out/sprites/images: every img/translation PNG, and each img/source frame without a translation.
    Each PSD in img/translation is dumped to a PNG of the same name in img/translation, and that PNG is used. A frame whose small-card box is still the original gets the B recoloured, except frames with a PSD in img/translation. Nothing else in the img folders is changed."""
    translation = ROOT / "img" / "translation"
    source = ROOT / "img" / "source"
    images = pathlib.Path(OUT, "images")
    shutil.rmtree(images, ignore_errors=True)
    images.mkdir(parents=True)
    psds = sorted(translation.glob("*.psd"))
    for psd in psds:
        psd_to_png(psd, translation / (psd.stem + ".png"))
    dumped = {psd.stem + ".png" for psd in psds}
    translated, recoloured = set(), 0
    for path in sorted(translation.glob("*.png")):
        translated.add(path.name)
        patched = None if path.name in dumped else smallcard_recoloured(path)
        if patched is None:
            shutil.copyfile(path, images / path.name)
        else:
            patched.save(images / path.name)
            recoloured += 1
    for path in sorted(source.glob("*.png")):
        if path.name in translated:
            continue
        patched = smallcard_recoloured(path)
        if patched is not None:
            patched.save(images / path.name)
            recoloured += 1
    say(f"sprite images: {len(translated)} from img/translation ({len(psds)} dumped from PSD), {recoloured} small cards recoloured")


@stage("save", "act", needs=("save-codes", "save-keys"))
def save():
    if len(command_args) not in (1, 2):
        sys.exit("использование: woh.py save [существующий save.ito] <выходной файл>")
    run_shown(sys.executable, "-I", ACT / "save_cheat.py", "out/save_codes.json", "out/save_keys.json", *command_args)


@stage("check", "act", needs=("extract-frames", "hook"))
def check():
    run_shown("uv", "run", CHECK / "test_translation_dimensions.py")
    run_shown(sys.executable, "-I", CHECK / "test_hook.py")
    run_shown(sys.executable, "-I", CHECK / "test_outputs.py")
    patched = common.OUTPUT / common.EXE
    if patched.exists():
        run_shown(sys.executable, "-I", CHECK / "image_check.py", patched)
        run_shown(sys.executable, "-I", CHECK / "check_patched.py", patched, common.TRANSLATION / "exe_strings.txt", "out/draw_hooks.tsv", "out/hook.json")


COMMANDS = ["build", "sync", "report", "extract", "ocr", "save", "check"]


def main():
    global game, literal, skipped, command_args, CACHE
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", help="папка игры (по умолчанию установка Steam)")
    parser.add_argument("--force", default="", help="этапы через запятую, которые нужно запустить заново, даже если их выходные данные есть")
    parser.add_argument("--literal", action="store_true", help="с build: также перенаправить собственные копии текстов exe, которые код не сравнивает")
    parser.add_argument("--no-exe", action="store_true", help="с build: не включать пропатченный worldofhorror.exe")
    parser.add_argument("--no-text", action="store_true", help="с build: не включать файлы языка")
    parser.add_argument("--no-sprites", action="store_true", help="с build: не включать data.win")
    parser.add_argument("--no-hashes", action="store_true", help="с build: не включать hashes.txt")
    parser.add_argument("command", choices=COMMANDS + ["list"])
    parser.add_argument("args", nargs="*", help="с save: [существующий save.ito] <выходной файл>")
    arguments = parser.parse_args()

    if arguments.command == "list":
        for name, (group, outputs, needs, _) in STAGES.items():
            print(f"{group:4} {name:18} {', '.join(outputs)}")
        return
    forced.update(filter(None, arguments.force.split(",")))
    unknown = forced - STAGES.keys()
    if unknown:
        sys.exit(f"unknown stage(s): {', '.join(sorted(unknown))}")
    literal, command_args = arguments.literal, [os.path.abspath(arg) for arg in arguments.args]
    skipped = {part for part, flag in (("exe", arguments.no_exe), ("text", arguments.no_text), ("sprites", arguments.no_sprites), ("hashes", arguments.no_hashes)) if flag}

    game = common.game_dir(arguments.game).resolve()
    common.require_pristine_game(game)
    CACHE = common.cache_dir(game).resolve()
    os.makedirs(CACHE / "out" / "logs", exist_ok=True)
    os.makedirs(CACHE / OUT, exist_ok=True)
    os.chdir(CACHE)  # the analysis scripts read and write relative `out/...` paths
    say(f"game {game}\ncache {CACHE}")
    started = time.time()
    build(arguments.command)
    say(f"finished in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
