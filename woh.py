# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow"]
# ///
"""Script that helps translate World of Horror.

Usage:
    uv run woh.py [--game DIRECTORY] [--force STAGE,STAGE] <command> [arguments]

Commands (each runs everything it needs):
    build [--no-exe] [--no-text] [--no-sprites] [--bundle [--profile PROFILE] [--target TRIPLE]]
                            writes language/engLanguage/*.jn, data.win and worldofhorror.exe to output/; refuses to write if the exe, or the
                            source frames and fonts of the translated images, changed since their hashes were recorded in hashes.txt
                            (a successful build records the new ones); each --no-* skips its part; copies the changelog (the root file
                            whose name ends with "СПИСОК ИЗМЕНЕНИЙ") to output/; --bundle writes <version>.zip in the root: the wohrus installer (built from installer/ with cargo; it holds patches against the game's files), the changelog, the instructions text and THIRD-PARTY-NOTICE.md,
                            the version being the text before the first space of the changelog's name;
                            the installer is built with the cargo profile PROFILE (default win-msvc-release) for the target TRIPLE (default: the host)
    sync                   update the tracked translation documents from the game (the only command that writes to tracked files);
                            exe_strings.txt is not changed: new exe texts go to the exe_strings_candidates.txt report in the build cache
    hashes                 accept the current game files: record their hashes in hashes.txt (after a game update, once the translations of the changed files are checked)
    extract                dump sprites and font atlases to img/source/
    ocr                    look for text in sprites
    save [INPUT] OUTPUT    generate a save with everything unlocked
    check                  run the checks
    list                   print the available commands

Game files are taken from the default Steam folder; use --game for another directory. The script needs a configured environment: GHIDRA_HEADLESS (path to the analyzeHeadless script), WOH_GHIDRA_JAVA (JAVA_HOME for Ghidra), UTMT_CLI (path to the UndertaleModCli binary).
Clang and uv are taken from PATH.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
PIPELINE = ROOT / "pipeline"
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "reverse"))
import common

REVERSE, GENERATE, ACT, CHECK = (
    PIPELINE / name for name in ("reverse", "generate", "act", "check")
)
OUT = "out/sprites"
DEBUG_VARIABLES = [
    "debug",
    "god_debug",
]  # assumed false; resolved to slot addresses by name from the exe
SAVE_DECOMPILE_TIMEOUT = "1800"
FRAMES_MARKER = ".build"  # in img/source: the cache directory whose frames it holds
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
SMALLCARD_RECOLOR = (
    (19, 14),
    (20, 15),
    (20, 14),
    (19, 15),
)  # (x, y) inside the box: black becomes white
_BLACK, _WHITE = (0, 0, 0, 255), (255, 255, 255, 255)
SMALLCARD_ORIGINAL = bytes(
    channel
    for row in SMALLCARD_BOX
    for cell in row
    for channel in (_BLACK if cell == "#" else _WHITE)
)

STAGES = {}  # name -> (group, outputs, needs, function), in definition order
INPUTS = {}  # name -> files outside the cache a stage reads: a newer one makes its outputs stale
done = set()
changed = set()  # stages whose outputs this run rewrote with different contents: what needs them runs again
forced = set()
game = None  # the game folder
skipped = set()  # build parts left out by --no-exe, --no-text, --no-sprites
bundle = False  # with build: pack the installer
cargo_profile = "win-msvc-release"  # cargo profile of the installer
cargo_target = None  # cargo --target of the installer; None: the host
command_args = []


def stage(name, group, *outputs, needs=(), inputs=()):
    def decorate(function):
        STAGES[name] = (group, outputs, needs, function)
        INPUTS[name] = inputs
        return function

    return decorate


def say(message):
    print(message, flush=True)


def build(name):
    """Run a stage after what it needs. A stage is current when its outputs exist, none of its `inputs` is newer than them and nothing it
    needs changed in this run. Editing a script does not invalidate them; use --force."""
    if name in done:
        return
    done.add(name)
    _group, outputs, needs, function = STAGES[name]
    for need in needs:
        build(need)
    files = [pathlib.Path(path) for path in outputs]
    if (
        files
        and name not in forced
        and all(path.exists() and path.stat().st_size > 0 for path in files)
    ):
        oldest = min(path.stat().st_mtime for path in files)
        stale = changed.intersection(needs) or any(
            path.stat().st_mtime > oldest for path in INPUTS[name]
        )
        if not stale:
            say(f"[{name}] current")
            return
    before = [common.sha256(path) if path.exists() else None for path in files]
    started = time.time()
    say(f"[{name}] ...")
    try:
        function()
    except BaseException:
        # a partial output must not pass as finished on the next run
        for path in files:
            path.unlink(missing_ok=True)
        raise
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        sys.exit(f"stage {name} did not write {', '.join(missing)}")
    if [common.sha256(path) for path in files] != before:
        changed.add(name)
    say(f"[{name}] done in {time.time() - started:.0f}s")


def run_python(script, *args, stdout=None):
    command = [sys.executable, "-I", str(script), *map(str, args)]
    log_path = pathlib.Path("out/logs", pathlib.Path(script).name + ".log")
    with (
        pathlib.Path(log_path).open("w", encoding="utf-8") as log,
        pathlib.Path(stdout).open("w", encoding="utf-8", newline="\n")
        if stdout
        else log as target,
    ):
        result = subprocess.run(
            command,
            stdout=target,
            stderr=log if stdout else subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode:
        sys.exit(f"failed: {' '.join(command)} (see {log_path.resolve()})")


def run_shown(*command, env=None, cwd=None):
    """An action: its output is what the user came for."""
    subprocess.run([str(part) for part in command], check=True, env=env, cwd=cwd)


def ghidra_env():
    env = dict(
        os.environ, GHIDRA_HEADLESS_MAXMEM="6G", MSYS_NO_PATHCONV="1"
    )  # the 2 GB default runs out of memory
    if os.environ.get("WOH_GHIDRA_JAVA"):
        env["JAVA_HOME"] = os.environ["WOH_GHIDRA_JAVA"]
    if "GHIDRA_HEADLESS" not in os.environ and not shutil.which("analyzeHeadless"):
        sys.exit("analyzeHeadless not found: set GHIDRA_HEADLESS")
    return env


def ghidra_command(*args):
    return [
        os.environ.get("GHIDRA_HEADLESS", "analyzeHeadless"),
        str(pathlib.Path("ghidra").resolve()),
        "woh",
        *args,
    ]


def run_ghidra_logged(log_name, command):
    log_path = pathlib.Path("out/logs", log_name + ".log")
    with pathlib.Path(log_path).open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=ghidra_env(),
            check=False,
        )  # DEVNULL: a launcher's `pause` returns instead of hanging
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if (
        result.returncode
        or " error:" in text
        or "SCRIPT ERROR" in text
        or "The class could not be found" in text
        or "OutOfMemoryError" in text
    ):
        tail = "\n".join(line for line in text.splitlines() if line.strip())[-1500:]
        sys.exit(
            f"Ghidra {log_name} failed (exit {result.returncode}, see {log_path.resolve()}):\n{tail}"
        )
    return text


def run_ghidra(script, *args):
    env_args = [
        str(pathlib.Path(arg).resolve()) if str(arg).startswith("out/") else str(arg)
        for arg in args
    ]  # analyzeHeadless may change directory
    os.environ["WOH_SYMBOLS"] = str(pathlib.Path("out/symbols.json").resolve())
    run_ghidra_logged(
        script,
        ghidra_command(
            "-process",
            common.EXE,
            "-noanalysis",
            "-readOnly",
            "-scriptPath",
            str(REVERSE),
            "-postScript",
            script,
            *env_args,
        ),
    )


def symbols():
    return json.load(pathlib.Path("out/symbols.json").open())


def rows(path):
    return [
        line.rstrip("\n").split("\t")
        for line in pathlib.Path(path).open(encoding="utf-8")
    ]


# ---------------------------------------------------------------- step 1: reverse engineering


@stage("ghidra-import", "re", "ghidra/imported.ok")
def ghidra_import():
    # a copy in the cache: analyzeHeadless.bat breaks on the `(x86)` and spaces of the Steam path
    pathlib.Path("ghidra").mkdir(exist_ok=True)
    copy = pathlib.Path("ghidra-input", common.EXE)
    copy.parent.mkdir(exist_ok=True)
    shutil.copyfile(game / common.EXE, copy)
    try:
        text = run_ghidra_logged(
            "ghidra-import",
            ghidra_command(
                "-import",
                str(copy.resolve()),
                "-overwrite",
                "-scriptPath",
                str(REVERSE),
                "-preScript",
                "FastAnalysis.java",
            ),
        )
    finally:
        shutil.rmtree(copy.parent)
    if "Save succeeded" not in text:  # an exited process is not enough
        sys.exit(
            "Ghidra import did not save the project (see out/logs/ghidra-import.log)"
        )
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
    run_ghidra(
        "ExportPoolStrings.java", f"{start:x}", str(end - start), "out/pool_strings.tsv"
    )


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


@stage("helpers", "re", "out/symbols.json", needs=("funcmap",))
def helpers():
    run_python(
        REVERSE / "resolve_helpers.py",
        game / common.EXE,
        OUT + "/funcmap.tsv",
        "out/symbols.json",
    )


@stage("config", "gen", "out/debug_slots.json", needs=("slots",))
def config():
    found = {}
    for address, name in rows(OUT + "/slots.tsv"):
        if name in DEBUG_VARIABLES:
            found.setdefault(name, []).append(address)
    for name in DEBUG_VARIABLES:
        if len(found.get(name, [])) != 1:
            sys.exit(
                f"variable `{name}` must have exactly one slot in the exe, found {found.get(name)}"
            )
    with pathlib.Path("out/debug_slots.json").open("w") as out:
        json.dump(
            {"debug_slots": [found[name][0] for name in DEBUG_VARIABLES]}, out, indent=1
        )


@stage(
    "scan-strings-plain",
    "re",
    OUT + "/strflow_plain.tsv",
    needs=("string-uses", "config", "helpers"),
)
def scan_strings_plain():
    """Flow.java following the string literals of targets.tsv (the slots StringUses.java found): which compares involve a known number and no string. The debug flags are assumed 0."""
    slots = sorted(
        {
            cols[1]
            for cols in rows("out/uses.uses.tsv")
            if len(cols) > 1 and cols[1] != "NOSLOT"
        }
    )
    pathlib.Path("out/string_slots.txt").write_text(
        "".join(slot + "\n" for slot in slots)
    )
    with pathlib.Path("out/debug_slots.json").open() as file:
        debug_slots = json.load(file)["debug_slots"]
    run_ghidra(
        "Flow.java",
        OUT + "/strflow_plain.tsv",
        *debug_slots,
        "strings",
        str(pathlib.Path("out/string_slots.txt").resolve()),
    )


@stage("decomp-save", "re", "out/decomp/save.ok", needs=("ghidra-import", "funcmap"))
def decomp_save():
    addresses = [
        address
        for address, name in rows(OUT + "/funcmap.tsv")
        if name == "gml_Script_endgame_check_achievements"
    ]
    if len(addresses) != 1:
        sys.exit(f"gml_Script_endgame_check_achievements: found {addresses}")
    run_ghidra("DecompBig.java", "out/decomp", SAVE_DECOMPILE_TIMEOUT, addresses[0])
    pathlib.Path("out/decomp/save.ok").write_text(addresses[0] + "\n")


# ---------------------------------------------------------------- step 2: artifacts


@stage("hook", "gen", "out/hook.bin", "out/hook.json")
def hook():
    run_python(GENERATE / "hook" / "build.py", "out")


@stage(
    "targets",
    "gen",
    "out/targets.tsv",
    needs=("pool-strings", "patch-sites"),
    inputs=(common.TRANSLATION / "exe_strings.txt",),
)
def targets():
    run_python(
        GENERATE / "make_targets.py",
        "out/pool_strings.tsv",
        common.TRANSLATION / "exe_strings.txt",
        "out/patch_sites.tsv",
        "out/targets.tsv",
    )


@stage(
    "usage",
    "gen",
    "out/usage.tsv",
    needs=("string-uses", "helpers", "scan-strings-plain", "slots"),
)
def usage():
    run_python(
        GENERATE / "classify_usage.py",
        "out/targets.tsv",
        "out/uses.uses.tsv",
        symbols()["compare"],
        "out/usage.tsv",
        OUT + "/strflow_plain.tsv",
        OUT + "/slots.tsv",
        game / common.EXE,
    )


@stage("save-codes", "gen", "out/save_codes.json", needs=("decomp-save",))
def save_codes():
    decompiled = [
        str(path)
        for path in pathlib.Path("out/decomp").glob("*.c")
        if not path.name.endswith(".named.c")
    ]
    if len(decompiled) != 1:
        sys.exit(f"out/decomp: expected one decompiled .c, found {decompiled}")
    run_python(REVERSE / "slotnames.py", game / common.EXE, *decompiled)
    run_python(
        GENERATE / "achiev_codes.py",
        decompiled[0][:-2] + ".named.c",
        "out/save_codes.json",
    )


@stage("save-keys", "gen", "out/save_keys.json", needs=("funcmap",))
def save_keys():
    addresses = [
        address
        for address, name in rows(OUT + "/funcmap.tsv")
        if name == "gml_Script_scr_systemsave"
    ]
    if len(addresses) != 1:
        sys.exit(f"gml_Script_scr_systemsave: found {addresses}")
    run_python(
        REVERSE / "inicalls.py",
        game / common.EXE,
        addresses[0],
        stdout="out/ini_calls.txt",
    )
    run_python(
        GENERATE / "save_keys.py",
        game / common.EXE,
        OUT + "/funcmap.tsv",
        "out/ini_calls.txt",
        "out/save_keys.json",
    )


def utmt():
    tool = os.environ.get("UTMT_CLI") or shutil.which("UndertaleModCli")
    if not tool:
        sys.exit("UndertaleModCli not found: set UTMT_CLI")
    return tool


@stage("extract-frames", "gen", "out/extract/sprites_manifest.tsv")
def extract_frames():
    frames_dir = ROOT / "img" / "source"
    shutil.rmtree(
        frames_dir, ignore_errors=True
    )  # img/source only ever holds one build's frames
    frames_dir.mkdir(parents=True)
    (
        frames_dir / "font"
    ).mkdir()  # the font atlases, written by the export next to the frames
    pathlib.Path("out/extract/fonts").mkdir(
        parents=True, exist_ok=True
    )  # the glyph tables
    env = dict(
        os.environ,
        WOH_OUT=str(pathlib.Path("out/extract").resolve()),
        WOH_SPRITES=str(frames_dir),
    )
    subprocess.run(
        [
            utmt(),
            "load",
            str(game / common.DATA_WIN),
            "-s",
            str(GENERATE / "export_woh.csx"),
        ],
        env=env,
        check=True,
        stdout=sys.stderr,
    )
    (frames_dir / FRAMES_MARKER).write_text(CACHE.name, encoding="utf-8")


@stage("ocr-text", "gen", "out/ocr_text.txt", needs=("extract-frames",))
def ocr_text():
    run_shown(
        "uv",
        "run",
        ACT / "ocr_sprites.py",
        "--out",
        str(pathlib.Path("out/ocr_text.txt").resolve()),
    )


# ---------------------------------------------------------------- step 3: actions (always run: they also depend on the authored files)


@stage("exe", "act", needs=("patch-sites", "draw-hooks", "hook"))
def exe():
    command = [sys.executable, "-I", ACT / "patch.py", "--game", game]
    with pathlib.Path(common.TRANSLATION / "exe_strings.txt").open(
        encoding="utf-8"
    ) as file:
        if any(
            common.parse_entry(line.rstrip("\n"))[0] for line in file
        ):  # marked entries are checked against usage.tsv and repointed via refs.tsv
            build("string-refs")
            build("usage")
    run_shown(*command)


@stage("text", "act")
def text():
    run_shown(
        sys.executable,
        "-I",
        ACT / "woh_txt.py",
        "apply",
        "--source",
        game / common.LANGUAGE,
    )


@stage("sprites", "act", needs=("sprite-images",))
def sprites():
    run_shown(
        sys.executable,
        "-I",
        ACT / "replace_sprites.py",
        "--images",
        str(pathlib.Path(OUT, "images").resolve()),
        "--data",
        game / common.DATA_WIN,
        "--utmt",
        utmt(),
    )


HASHED = {
    "exe": lambda name: name == common.EXE,
    "sprites": lambda name: name.endswith(".png"),
}  # the hashes.txt lines each part of the build owns


def source_hashes(part):
    """sha256 of the game files a part of the build is made from, [(digest, name)]: the exe for "exe"; for "sprites" each extracted frame in img/source that has a
    PNG of the same name in img/translation, and each extracted font atlas (font/<name>.png) that has one in img/translation/font: the game's original pixels."""
    if part == "exe":
        return [(common.sha256(game / common.EXE), common.EXE)]
    build("extract-frames")
    entries = []
    for subfolder in ("", "font"):
        source, translation = (
            ROOT / "img" / "source" / subfolder,
            ROOT / "img" / "translation" / subfolder,
        )
        names = sorted(path.name for path in translation.glob("*.png"))
        missing = [name for name in names if not (source / name).is_file()]
        if missing:
            sys.exit(
                f"not in {source.relative_to(ROOT).as_posix()}: {', '.join(missing)}"
            )
        prefix = subfolder + "/" if subfolder else ""
        entries += [(common.sha256(source / name), prefix + name) for name in names]
    return entries


def checked_hashes(parts):
    """The hashes of the sources of these parts, after checking them against hashes.txt: a source that changed since its hash was recorded stops the run
    before anything is written. `woh.py hashes` accepts the new game files."""
    current = {part: source_hashes(part) for part in parts}
    stale = common.changed_hashes(
        {name: digest for entries in current.values() for digest, name in entries}
    )
    if stale:
        sys.exit(
            "changed since their hashes were recorded in hashes.txt, nothing was written:\n  "
            + "\n  ".join(stale)
            + "\nThe game was updated. Review the translations of these files, then run `woh.py hashes` to record the new hashes."
        )
    return current


def changelog():
    """The root file whose name, without its extension, ends with "СПИСОК ИЗМЕНЕНИЙ"."""
    found = [
        path
        for path in ROOT.iterdir()
        if path.is_file() and path.stem.endswith("СПИСОК ИЗМЕНЕНИЙ")
    ]
    if len(found) != 1:
        sys.exit(
            f"expected one changelog in {ROOT} (name ending with СПИСОК ИЗМЕНЕНИЙ), found {len(found)}"
        )
    return found[0]


def make_bundle(version, changelog_file):
    """<version>.zip in the root (standard deflate) with the installer, the changelog, the instructions text and THIRD-PARTY-NOTICE.md (cargo-about, from installer/about.toml and about.hbs; the licenses of the Rust crates linked into the installer). The installer is built from installer/ with cargo; woh-pack
    appends to it a pack of bsdiff patches of data.win and the exe (against the game's files) plus the other files of output/ except the changelog, so the user needs
    the same game version, not a copy of its files."""
    # cargo reads installer/.cargo/config.toml (scalar CPU flags) from the working directory, not from the manifest path
    run_shown(
        "cargo",
        "build",
        "--profile",
        cargo_profile,
        *(("--target", cargo_target) if cargo_target else ()),
        cwd=ROOT / "installer",
    )
    release = ROOT / "installer" / "target"
    if cargo_target:
        release /= cargo_target
    release /= cargo_profile
    suffix = ".exe" if sys.platform == "win32" else ""
    with tempfile.TemporaryDirectory() as tmp:
        installer = pathlib.Path(tmp) / f"wohrus{suffix}"
        notice = pathlib.Path(tmp) / "THIRD-PARTY-NOTICE.md"
        readme = (
            ROOT / "installer" / "ПРИМЕНЕНИЕ ПЕРЕВОДА - ЧИТАЙ.txt"
        )  # instructions for the user, kept in the repo
        run_shown(
            "cargo",
            "about",
            "generate",
            "about.hbs",
            "-m",
            "cli/Cargo.toml",
            "-o",
            notice,
            cwd=ROOT / "installer",
        )
        run_shown(
            release / f"woh-pack{suffix}",
            "--pristine",
            game,
            "--built",
            common.OUTPUT,
            "--exclude",
            changelog_file.name,
            "--version",
            version,
            "--installer",
            release / f"wohrus{suffix}",
            "--out",
            installer,
        )
        out = ROOT / f"{version}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(installer, installer.name)
            archive.write(changelog_file, changelog_file.name)
            archive.write(notice, notice.name)
            archive.write(readme, readme.name)
    say(f"bundle: {out}")


@stage("build", "act")
def build_output():
    parts = [part for part in ("exe", "sprites") if part not in skipped]
    current = checked_hashes(
        parts
    )  # first: the sprites need only the extracted frames, not Ghidra
    for part in ("exe", "text", "sprites"):
        if part not in skipped:
            build(part)
    for part in parts:  # after the outputs were written: records the sources of new translations and drops those of deleted ones
        common.record_hashes(HASHED[part], current[part])
    source = changelog()
    common.OUTPUT.mkdir(parents=True, exist_ok=True)  # all parts may have been skipped
    shutil.copy2(source, common.OUTPUT / source.name)
    say(f"output: {common.OUTPUT}")
    if bundle:
        make_bundle(source.name.partition(" ")[0], source)


@stage("hashes", "act")
def accept_hashes():
    for part in (
        "exe",
        "sprites",
    ):  # the current game files are accepted: their hashes replace the recorded ones
        common.record_hashes(HASHED[part], source_hashes(part))
    say(f"hashes.txt: {common.HASHES}")


@stage("sync", "act", needs=("targets",))
def sync():
    run_shown(
        sys.executable,
        "-I",
        ACT / "woh_txt.py",
        "carry",
        "--source",
        game / common.LANGUAGE,
    )
    run_shown(
        sys.executable,
        "-I",
        ACT / "exe_strings.py",
        "out/targets.tsv",
        "out/exe_strings_candidates.txt",
    )


@stage("extract", "act", needs=("extract-frames",))
def extract():
    say(
        f"frames and font atlases: {ROOT / 'img' / 'source'}; glyph tables: {CACHE / 'out' / 'extract' / 'fonts'}"
    )


@stage("ocr", "act", needs=("ocr-text",))
def ocr():
    say(f"OCR text: {CACHE / 'out' / 'ocr_text.txt'}")


def smallcard_recoloured(path):
    """The image at path as RGBA with the small-card B recoloured, or None when its box is not the original."""
    from PIL import Image  # Pillow, declared in the script header

    box = (
        SMALLCARD_X,
        SMALLCARD_Y,
        SMALLCARD_X + SMALLCARD_SIZE,
        SMALLCARD_Y + SMALLCARD_SIZE,
    )
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
    """The PNGs that sprites writes into data.win, in out/sprites/images: every img/translation PNG, and each img/source frame without a translation whose small-card B needs recolouring.
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
    say(
        f"sprite images: {len(translated)} from img/translation ({len(psds)} dumped from PSD), {recoloured} small cards recoloured"
    )


@stage("save", "act", needs=("save-codes", "save-keys"))
def save():
    if len(command_args) not in (1, 2):
        sys.exit("usage: woh.py save [existing save.ito] <output file>")
    run_shown(
        sys.executable,
        "-I",
        ACT / "save_cheat.py",
        "out/save_codes.json",
        "out/save_keys.json",
        *command_args,
    )


@stage("check", "act", needs=("extract-frames", "hook"))
def check():
    run_shown("uv", "run", CHECK / "test_translation_dimensions.py")
    run_shown(
        "uv",
        "run",
        CHECK / "font_check.py",
        ROOT / "img" / "translation" / "font",
        ROOT / "img" / "source" / "font",
        "out/extract/fonts",
    )
    run_shown(sys.executable, "-I", CHECK / "test_hook.py")
    run_shown(sys.executable, "-I", CHECK / "test_outputs.py")
    patched = common.OUTPUT / common.EXE
    if patched.exists():
        run_shown(sys.executable, "-I", CHECK / "image_check.py", patched)
        run_shown(
            sys.executable,
            "-I",
            CHECK / "check_patched.py",
            patched,
            common.TRANSLATION / "exe_strings.txt",
            "out/draw_hooks.tsv",
            "out/hook.json",
        )


COMMANDS = ["build", "sync", "hashes", "extract", "ocr", "save", "check"]


def main():
    global game, skipped, bundle, cargo_profile, cargo_target, command_args, CACHE
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--game", help="game folder (default: the Steam install)")
    parser.add_argument(
        "--force",
        default="",
        help="comma-separated stages to rerun even if their outputs exist",
    )
    parser.add_argument(
        "--no-exe",
        action="store_true",
        help="with build: do not include the patched worldofhorror.exe",
    )
    parser.add_argument(
        "--no-text",
        action="store_true",
        help="with build: do not include the language files",
    )
    parser.add_argument(
        "--no-sprites", action="store_true", help="with build: do not include data.win"
    )
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="with build: write <version>.zip (installer and changelog) in the project root",
    )
    parser.add_argument(
        "--profile",
        default=cargo_profile,
        help="with --bundle: cargo profile of the installer (default: %(default)s)",
    )
    parser.add_argument(
        "--target",
        help="with --bundle: cargo target triple of the installer (default: the host)",
    )
    parser.add_argument("command", choices=[*COMMANDS, "list"])
    parser.add_argument(
        "args", nargs="*", help="with save: [existing save.ito] <output file>"
    )
    arguments = parser.parse_args()

    if arguments.command == "list":
        for name, (group, outputs, _needs, _) in STAGES.items():
            print(f"{group:4} {name:18} {', '.join(outputs)}")
        return
    forced.update(filter(None, arguments.force.split(",")))
    unknown = forced - STAGES.keys()
    if unknown:
        sys.exit(f"unknown stage(s): {', '.join(sorted(unknown))}")
    command_args = [str(pathlib.Path(arg).resolve()) for arg in arguments.args]
    skipped = {
        part
        for part, flag in (
            ("exe", arguments.no_exe),
            ("text", arguments.no_text),
            ("sprites", arguments.no_sprites),
        )
        if flag
    }
    bundle = arguments.bundle
    cargo_profile = arguments.profile
    cargo_target = arguments.target

    game = common.game_dir(arguments.game).resolve()
    common.require_pristine_game(game)
    CACHE = common.cache_dir(game).resolve()
    (CACHE / "out" / "logs").mkdir(parents=True, exist_ok=True)
    (CACHE / OUT).mkdir(parents=True, exist_ok=True)
    marker = ROOT / "img" / "source" / FRAMES_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != CACHE.name:
        forced.add("extract-frames")  # img/source holds another build's frames, or none
    os.chdir(CACHE)  # the analysis scripts read and write relative `out/...` paths
    say(f"game {game}\ncache {CACHE}")
    started = time.time()
    build(arguments.command)
    say(f"finished in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
