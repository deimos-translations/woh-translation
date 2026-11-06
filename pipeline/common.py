"""Общее для скриптов конвейера: где находится игра, кэш одной сборки и защита от использования собственного вывода как входных данных."""
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
STEAM = (pathlib.Path(r"C:\Program Files (x86)\Steam\steamapps\common\WOH") if sys.platform == "win32"
         else pathlib.Path.home() / ".local/share/Steam/steamapps/common/WOH")
PATCH_SECTIONS = {b".ruloc", b".ruhook"}  # patch.py appends these to the exe
LABEL_KEYS = ["DOOM", "STA", "REA", "ALL"]  # battle damage labels: logic keys that patch.py and make_targets treat specially
SEPARATOR = "|"
_PRODUCED = BUILD / "produced.md5"
HASHES = ROOT / "hashes.txt"  # tracked: <sha256><TAB><file name> lines for the exe and the translated sprites


@functools.cache  # one process hashes the same game file several times (guard, cache key, ...)
def md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256(path):
    with open(path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def data_win_chunks(data):
    """Offset of the contents of each chunk of a data.win, by its four-letter tag."""
    chunks, position = {}, 8
    while position < len(data):
        chunks[data[position:position + 4].decode("latin1")] = position + 8
        position += 8 + struct.unpack_from("<I", data, position + 4)[0]
    return chunks


UNESCAPES = {"\\\\": "\\", "\\r": "\r", "\\n": "\n", "\\t": "\t"}


def unescape(text):
    """Undo the `\\\\`, `\\r`, `\\n`, `\\t` escapes of the translation documents."""
    return re.sub(r"\\[\\rnt]", lambda match: UNESCAPES[match.group()], text)


def record_hashes(suffix, entries):
    """Replace the hashes.txt lines whose file name ends with suffix by entries ((sha256, name) pairs); other lines stay."""
    kept = []
    if HASHES.exists():
        kept = [line for line in HASHES.read_text(encoding="utf-8").splitlines() if line and not line.partition("\t")[2].endswith(suffix)]
    lines = kept + [f"{digest}\t{name}" for digest, name in entries]
    HASHES.write_text("".join(f"{line}\n" for line in sorted(lines, key=lambda line: line.partition("\t")[2])), encoding="utf-8", newline="\n")


def game_dir(game=None):
    path = pathlib.Path(game) if game else STEAM
    if not (path / EXE).is_file():
        sys.exit(f"{EXE} not found in {path}: install the game there or pass --game DIR")
    return path


def cache_dir(game):
    """The ignored directory holding everything derived from this exact exe and data.win."""
    return BUILD / f"{md5(game / EXE)[:8]}-{md5(game / DATA_WIN)[:8]}"


def section_names(exe_bytes):
    pe = struct.unpack_from("<I", exe_bytes, 0x3C)[0]
    count, optional_size = struct.unpack_from("<H", exe_bytes, pe + 6)[0], struct.unpack_from("<H", exe_bytes, pe + 20)[0]
    table = pe + 24 + optional_size
    return {bytes(exe_bytes[table + 40 * i:table + 40 * i + 8]).rstrip(b"\0") for i in range(count)}


def _produced():
    return set(_PRODUCED.read_text().split()) if _PRODUCED.exists() else set()


def record_produced(*paths):
    BUILD.mkdir(exist_ok=True)
    with open(_PRODUCED, "a") as out:
        out.writelines(md5(path) + "\n" for path in paths)


def require_pristine(path):
    """Refuse a file this pipeline wrote: an installed translation must never be analysed or translated as if it were the original."""
    if md5(path) in _produced():
        sys.exit(f"{path} is output of this pipeline, not the original game file. Run Steam's \"Verify integrity of game files\".")


def require_pristine_game(game):
    if section_names((game / EXE).read_bytes()) & PATCH_SECTIONS:
        sys.exit(f"{game / EXE} is a patched exe. Run Steam's \"Verify integrity of game files\".")
    for path in (game / EXE, game / DATA_WIN, *sorted((game / LANGUAGE).glob("*.jn"))):
        require_pristine(path)
