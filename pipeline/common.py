"""Shared by the pipeline scripts: where the game is, the cache of a single build, and a guard against using their own output as input."""

import functools
import hashlib
import pathlib
import re
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
OUTPUT = ROOT / "output"
TRANSLATION = ROOT / "translation"
LANGUAGE = pathlib.PurePosixPath("language", "engLanguage")
EXE = "worldofhorror.exe"
DATA_WIN = "data.win"
STEAM = (
    pathlib.Path(r"C:\Program Files (x86)\Steam\steamapps\common\WOH")
    if sys.platform == "win32"
    else pathlib.Path.home() / ".local/share/Steam/steamapps/common/WOH"
)
PATCH_SECTIONS = {".ruloc", ".ruhook"}  # patch.py appends these to the exe
LABEL_KEYS = [
    "DOOM",
    "STA",
    "REA",
    "ALL",
]  # battle damage labels: logic keys that patch.py and make_targets treat specially
SEPARATOR = "|"
_PRODUCED = BUILD / "produced.md5"
HASHES = (
    ROOT / "hashes.txt"
)  # tracked: <sha256><TAB><file name> lines for the exe and the translated sprites


@functools.cache  # one process hashes the same game file several times (guard, cache key, ...)
def md5(path):
    digest = hashlib.md5()
    with pathlib.Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256(path):
    with pathlib.Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


UNESCAPES = {
    "\\\\": "\\",
    "\\r": "\r",
    "\\n": "\r\n",
    "\\l": "\n",
    "\\t": "\t",
    "\\!": "!",
}
POOL_UNESCAPES = {
    "\\\\": "\\",
    "\\r": "\r",
    "\\n": "\n",
    "\\t": "\t",
}  # ExportPoolStrings.java writes CR and LF separately
LITERAL_MARK = "!"  # exe_strings.txt: a line starting with it also has the exe's own copies of its source replaced (patch.py)


def unescape(text):
    """Undo the escapes of the translation documents: `\\\\` backslash, `\\n` CRLF (the game's line break), `\\l` bare LF, `\\r` bare CR, `\\t` TAB,
    `\\!` an exclamation mark (a source that starts with `!` is written `\\!` in exe_strings.txt, where a leading `!` is the literal mark)."""
    return re.sub(r"\\[\\rnlt!]", lambda match: UNESCAPES[match.group()], text)


def parse_entry(line):
    """One exe_strings.txt line without its line break -> (literal, source, has_separator, translation); source and translation stay escaped."""
    literal = line.startswith(LITERAL_MARK)
    source, separator, translation = line[literal:].partition(SEPARATOR)
    return literal, source, bool(separator), translation


def escape(text):
    """Inverse of unescape: a game text as it is written in the documents, so CRLF is `\\n` and the documents hold no `\\r\\n`."""
    return (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\l")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def unescape_pool(text):
    """Undo the escapes of pool_strings.tsv: `\\\\`, `\\r`, `\\n` (LF), `\\t`."""
    return re.sub(r"\\[\\rnt]", lambda match: POOL_UNESCAPES[match.group()], text)


def record_hashes(owned, entries):
    """Replace the hashes.txt lines whose file name owned(name) accepts by entries ((sha256, name) pairs); other lines stay."""
    kept = []
    if HASHES.exists():
        kept = [
            line
            for line in HASHES.read_text(encoding="utf-8").splitlines()
            if line and not owned(line.partition("\t")[2])
        ]
    lines = kept + [f"{digest}\t{name}" for digest, name in entries]
    HASHES.write_text(
        "".join(
            f"{line}\n"
            for line in sorted(lines, key=lambda line: line.partition("\t")[2])
        ),
        encoding="utf-8",
        newline="\n",
    )


def read_hashes():
    """hashes.txt as {file name: sha256}."""
    if not HASHES.exists():
        return {}
    return {
        name: digest
        for digest, _, name in (
            line.partition("\t")
            for line in HASHES.read_text(encoding="utf-8").splitlines()
            if line
        )
    }


def changed_hashes(current):
    """The names in current ({file name: sha256}) whose recorded hash in hashes.txt is different. A name that is not recorded yet is not changed."""
    recorded = read_hashes()
    return sorted(
        name for name, digest in current.items() if recorded.get(name, digest) != digest
    )


def game_dir(game=None):
    path = pathlib.Path(game) if game else STEAM
    if not (path / EXE).is_file():
        sys.exit(
            f"{EXE} not found in {path}: install the game there or pass --game DIR"
        )
    return path


def cache_dir(game):
    """The ignored directory holding everything derived from this exact exe and data.win."""
    return BUILD / f"{md5(game / EXE)[:8]}-{md5(game / DATA_WIN)[:8]}"


def pe_sections(data):
    """{name: (virtual size, RVA, raw size, raw offset)} of the sections of a PE image."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count, optional_size = (
        struct.unpack_from("<H", data, pe + 6)[0],
        struct.unpack_from("<H", data, pe + 20)[0],
    )
    table = pe + 24 + optional_size
    return {
        bytes(data[header : header + 8]).rstrip(b"\0").decode(): struct.unpack_from(
            "<IIII", data, header + 8
        )
        for header in (table + 40 * index for index in range(count))
    }


def _produced():
    return set(_PRODUCED.read_text().split()) if _PRODUCED.exists() else set()


def record_produced(*paths):
    BUILD.mkdir(exist_ok=True)
    new = {md5(path) for path in paths} - _produced()
    if new:
        with pathlib.Path(_PRODUCED).open("a") as out:
            out.writelines(digest + "\n" for digest in sorted(new))


def require_pristine(path):
    """Refuse a file this pipeline wrote: an installed translation must never be analysed or translated as if it were the original."""
    if md5(path) in _produced():
        sys.exit(
            f'{path} is output of this pipeline, not the original game file. Run Steam\'s "Verify integrity of game files".'
        )


def require_pristine_game(game):
    if pe_sections((game / EXE).read_bytes()).keys() & PATCH_SECTIONS:
        sys.exit(
            f'{game / EXE} is a patched exe. Run Steam\'s "Verify integrity of game files".'
        )
    for path in (game / EXE, game / DATA_WIN, *sorted((game / LANGUAGE).glob("*.jn"))):
        require_pristine(path)
