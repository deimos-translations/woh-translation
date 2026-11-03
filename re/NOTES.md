# worldofhorror.exe reverse engineering notes

Target: `worldofhorror.exe` (PE32+ x64, GameMaker YYC build). Addresses, function names (`FUN_...`), md5s and counts change with every
build and are deliberately not recorded here; they live in the generated files (`re/build.md5`, `re/patch_sites.tsv`,
`re/draw_hooks.tsv`, `re/strings/*.tsv`) and are found again by the scripts. Statements are observed unless marked.

## Setup

- REA's Ghidra provider is unusable (needs Ghidra 12.1.x, installed is 12.2). Ghidra headless is driven directly.
- `analyzeHeadless.bat` breaks on `(x86)` in the Steam path: import a copy of the exe from a scratch dir.
- Set `GHIDRA_HEADLESS_MAXMEM=6G` (the 2 GB default OOMs) and `JAVA_HOME=C:\PATH\java`. Under Git Bash also set `MSYS_NO_PATHCONV=1`,
  otherwise script args starting with `/` are rewritten into paths.
- `-preScript FastAnalysis.java` switches off Decompiler Switch Analysis, Stack, Function ID and Variadic Function Signature Override
  (none are needed) and more than halves the analysis time.
- One project per build in `re/ghidra`, program `worldofhorror.exe`; `re/build.md5` says which exe the generated files belong to.
- Scripts live in `re/scripts`, run with
  `-process worldofhorror.exe -noanalysis -readOnly -scriptPath re/scripts -postScript <Script>.java <outPath> <args>`:
  `StringRefs` (literal -> referencing functions, decompiled), `SlotReaders` (literal -> startup slot -> users), `SlotContext`
  (disassembly around slot reads), `FuncStrings` (strings used by a function), `DumpAsm`, `FuncOnly`, `AddrRefs`, `RefsTo`,
  `StringUses`, `DecompBig` (decompile with a long timeout).
- The decompiler times out on very large functions (the draw events, `scr_systemload`): use `DumpAsm` / `SlotContext`, or
  `DecompBig`. Raw outputs go to `re/out/`.

## How GML string literals are stored

- Each literal is a NUL-terminated UTF-8 blob in `.rdata`.
- Per-script static initializers run at startup: a string-object constructor is called with `(&slot, "text")`, followed by an atexit
  registration. The constructor allocates a 16-byte string object `{ char* ptr; ...; uint len = strlen(ptr) | 0x80000000; refcount = 1 }`
  and stores it in a global `slot` (16-byte value, tag 1 = string).
- Length is computed by a runtime strlen, so **a replacement string can be any length**. Only the pointer must reach it. The size limit
  of in-place hex editing belongs to the editing method, not to the engine.
- Literals are not deduplicated across scripts: a text has several copies (e.g. `STA`, `REA`, `ALL`), each owned by one script's initializer.
- A string copy can directly follow a binary constant, so a byte scan for NUL-preceded text misses it. Find copies through code
  references, not through byte patterns.
- Runtime helpers (names differ per build): value comparison (0 = equal), array indexing, value assign, number multiply/add, `+=`,
  call-by-index wrapper, debug print.
- Builtin calls look like `call(self, other, &ret, argc, builtin_id_slot, args)`; a builtin id slot is 16 bytes in `.data` and its name
  pointer sits 8 bytes BEFORE it.

## STA / REA / ALL in battle

Battle damage type is a string value: `"STA"` / `"REA"` / `"ALL"` (also `"DOOM"`, `"stamina damage"`, `"injury"`, `"curse"`).
The `.jn` entries `STA|STA` / `REA|REA` (`woh_dec.jn`) are used only on the character status screen.

Producers (assign the literal as an argument/value; the slot is only address-taken):
- `gml_Script_customenemy_init`: builds each custom enemy attack with a 3-argument script call whose third argument is the type literal.
- Other copies belong to `gml_Object_nenm_xxx_*` / enemy definition scripts (`re/out/slot_readers.txt`).

Consumers (read the slot and compare it):
- `gml_Script_newcombat_penalty`: game logic. Compares the penalty type with `STA`, `stamina damage`, `REA`, `ALL`, `DOOM`, `injury`,
  `curse` and applies the effect. **These comparisons must keep matching the producers.**
- `gml_Object_parent_newcombat_Draw_0`, `gml_Object_nenm_xxx_custom_Draw_0`, `gml_Object_nenm_xxx_custom_ext_Draw_0`: drawing code.

Editing a shared literal breaks logic, because the English path draws the key itself (label = type). Earlier in-place hex edits of `REA`
probably broke battles by changing only some copies (producers and `newcombat_penalty` then disagree). Unconfirmed.

### The `lang == 7` label block in the draw events

- The exe stores per-language labels next to the keys, e.g. `DOOM`/`ZGŁ`, `STA`/`KND`, `REA`/`RZS`, `ALL`/`WSZ`, then `VDBN`, `AUS`, `VNF`.
- Each of the three draw events has exactly one `if (lang == 7.0)` block (about 3 KB) covering the `DOOM`/`STA`/`REA`/`ALL` slots. It
  contains only compares and label assignments; `label = type` happens before it, so the English path draws the raw type. Other
  branches (`lang == 1..6`) hold labels for other languages.
- The language is a local read from a global variable id and compared with double constants 1..7 (`7.0` = `MOV RAX,0x401c000000000000`).
- Inference, not proven by running the game: that global is the language index. Evidence: the `.jn` loader reads the same variable;
  the constants follow the exe's language table order (`eng, jap, cht, chs, kor, fra, ger, pol, ukr, tur`), 7 = pol, and the labels
  are Polish abbreviations.
- Sites (guard `0F 85 rel32` per event, twelve `LEA RDX,[rip+disp32]` label loads) are in `re/patch_sites.tsv`.

## Patch (statically verified, NOT run in the game)

`python -I re/patch.py <original exe> <output exe> [re/strings/strings.txt]` (reads `re/patch_sites.tsv`; output goes to `re/out/`, never
overwrites the input; refuses an exe whose md5 differs from `re/build.md5`):
1. NOPs the three `lang == 7` guards so the label block runs for every language.
2. Repoints the label loads at UTF-8 text in a new `.ruloc` section. The text comes from the first four lines of
   `re/strings/strings.txt` (`DOOM`, `STA`, `REA`, `ALL`). An empty entry keeps its English key as the label; if all four are empty the
   guards and loads are left alone. Any length works.
3. Translated hardcoded strings go through the draw-time hook (below), added to the same output. `--literal` (optional) additionally
   repoints the exe's own copies (see next section).

Logic literals are untouched. The PE has no signature or overlay and enough header slack to append a section. The block was judged
label-only from disassembly. Not tested at runtime.

## Translating hardcoded strings (NOT run in the game)

- `re/strings/targets.tsv`: candidate strings and all their copies (VA, escaped text), built by `re/scripts/make_targets.py` from
  `ExportPoolStrings.java` (every code-referenced string). Selection: multi-word text minus debug/mod-tool strings, plus short ALL-CAPS
  tokens (`PREP`, `S.ATK`, `MAGIC`, ...) and quoted ALL-CAPS names (`'HAPPY LEMON'`), excluding the damage-type keys and label strings
  `patch.py` handles. Single-token strings must not be dropped as identifiers.
- `re/strings/refs.tsv`: every code reference to those copies, from `re/scripts/ExportStringRefs.java`. Only RIP-relative `lea` is used;
  `mov` entries are Ghidra value propagation and are ignored. Texts without a `lea` reference (the two-letter `MC`..`CC` codes, odd
  fragments) can not be changed by `patch.py`, which warns if one is translated.
- `re/strings/strings.txt`: the document, `source<#>translation`, one line per distinct string; `python -I re/strings.py` refreshes it
  and keeps existing translations. Escapes: `\`, `\r`, `\n`, `\t`; `#` is the game's line break. Empty translation = untouched.
- `patch.py --literal` repoints every copy's loads at the translation in `.ruloc`. Any length. It is the fallback for text modified
  before drawing, at the cost of the logic guarantee, and is refused for compared texts.
- Being in the document does not make a string safe to translate: some are logic keys (`SVR KICK`, `ALLY ATK`, `NO CASH`) compared
  against values created elsewhere. Unverified per string.

## Safety research: will a translation change behaviour?

- No code reference lands inside a target string (`StringUses.java`, `interior`): replacing a string start moves every reference to it.
- Usage classes (`StringUses.java` + `classify_usage.py` -> `re/strings/usage.tsv`): `logic` = tested with the compare helper right
  after the load (e.g. `SVR KICK`, `ALLY ATK`, `LOOK FOR#A WEAK SPOT`, `PREP`); the rest are not compared near the load.
- `PREP` etc. are action IDs: `combat_loadactions` / `combat_clickactions` build arrays like `["PREP", 20*i, 40*j]`, `combat_action`
  compares the ID, and the same string is the button text. Text and key are one value.
- Replacing every copy guarantees that comparisons between values that both originate from exe literals stay equal. It does not
  guarantee (unproven): a value persisted (save file, ini) and read back after the patch; a string used for content-dependent work
  (length, characters, building asset/variable names); a counterpart that lives in `data.win`.
- A real guarantee needs the logic values left untouched and the text swapped only at draw time: the hook below.

## Draw-time translation hook (tested natively, NOT run in the game)

Logic values are never changed; the text argument of the text-drawing built-ins is swapped for the duration of the call.
- **Where:** the runtime registers every built-in with `register(name, function, argc, flag)`, the function loaded by `LEA RDX,[rip+d]`
  (`FindDrawHooks.java` -> `re/draw_hooks.tsv`). Hooked: `draw_text*` (text = argument 2) and `string_width/height[_ext]` (argument 0).
  Each implementation is referenced only by this `lea` and its `.pdata` record, so every call goes through the registered pointer
  (checked with `RefsTo.java`). Calls come through the call-by-index wrapper, which copies the arguments into a private array on its
  stack and passes it as the fifth argument.
- **Runtime layout:** RValue = {value @0, flags @8, kind @0xc (low 24 bits)}; kind 1 = string; value -> RefString {char* @0,
  refcount @8, size @0xc}; the game's own constants use refcount 1 and size = length|0x80000000.
- **Hook** (`re/hook/hook.s`): a stub `lea r10,[info]; jmp common` per site; `common` checks argc > index and kind == string, FNV-1a
  hashes the text, probes the table, on a hit stores the translation's address into a static RefString and puts that in the argument
  slot, calls the original, then restores the original value pointer. No absolute addresses (the table holds offsets, the translation
  address is stored at hit time), so no relocations are needed. An unwind entry (`UNWIND_ALLOC_0x48`) is appended to `.pdata` so
  exceptions can pass through.
- **Layout of the patched exe:** `.ruloc` (RW: label text, table, strings, unwind info) then `.ruhook` (RX: hook, stubs, infos).
- **Tests:** `re/hook/test_hook.py` runs the real `hook.bin` against a fake built-in (hits, misses, collisions, control characters,
  non-strings, argc too small, restore, stack alignment). `re/hook/check_patched.py <patched exe> <strings.txt>` runs the patched
  exe's own stubs/table/code for every hooked built-in and checks the `.pdata` entry (needs clang tools on PATH). `re/hook/image_check.py`
  asks the Windows loader (`CreateFileMapping` with `SEC_IMAGE`, no execution) whether the file is a valid image; error 193 = malformed PE.
  Rebuild the hook with `re/hook/build.py` (clang on PATH, `C:\msys64\clang64\bin`).
- **Limits:** only a string passed WHOLE to one of the hooked built-ins is translated (text built by concatenation or changed by a script
  before drawing is not); a translation longer than the original may overflow a layout; `string_width` of a translated text is measured
  on the translation (good), but code that measures the original and draws with the hook sees different widths.

## After a game update

`re/build.md5` holds the md5 of the exe that `re/patch_sites.tsv`, `re/draw_hooks.tsv` and `re/strings/{targets,refs}.tsv` belong to;
`patch.py` refuses any other file. Each step is scripted; the Ghidra analysis is the only slow one.
1. Copy the exe to a scratch dir and import it as a new project:
   `analyzeHeadless re/ghidra <name> -import <copy> -overwrite -scriptPath re/scripts -preScript FastAnalysis.java`.
   Wait for `Save succeeded` in the log (a `java.exe` that has exited is not enough; look for `OutOfMemoryError`).
2. `-process worldofhorror.exe -noanalysis -readOnly -postScript FindPatchSites.java re/patch_sites.tsv`
   (finds the three draw events by name, their DOOM/STA/REA/ALL slots, label slots and guards).
3. `-postScript ExportPoolStrings.java <pool start VA> 300000 re/out/pool_strings.tsv` (pool start = .rdata VA + 3648 on the builds seen;
   every code-referenced string), then
   `python -I re/scripts/make_targets.py <exe> re/out/pool_strings.tsv re/strings/targets.tsv re/strings/targets.tsv` (copy the old
   file elsewhere first for a diff; it prints missing texts and changed copy counts), then
   `-postScript ExportStringRefs.java re/strings/targets.tsv re/strings/refs.tsv`.
4. `-postScript FindDrawHooks.java re/draw_hooks.tsv`.
5. Write the new md5 to `re/build.md5`, run `python -I re/strings.py`, then `patch.py`.

If `FindPatchSites` throws, the draw events changed shape: read its exception message and `DumpAsm.java` the event.

Not scanned: strings under 2 characters, UTF-16 text, mixed-case single words (almost all keyboard-mash cheat sequences), multi-word
strings containing dev words (nearly all debug text), and `data.win`.

## Save file (static analysis; the file format is confirmed against a real game-written `save.ito`, unlocks NOT yet confirmed in the game)

- The save is the plain-text INI `%LOCALAPPDATA%\wohgame\save.ito` (GameMaker save area; GEN8 name `wohgame`), CRLF, `key="value"` (reals are written
  quoted, e.g. `"0.000000"`). `scr_systemload` calls `scr_openini("save.ito")` (= `ini_open`) on PC and then reads every key directly into globals
  (`achiev[r][c] = ini_read_string("achievement", "r,c", "")`, reals via the native `ini_read_real`). `scr_systemsave` writes the same keys with
  `ini_write_string` / `ini_write_real` and `ini_close` writes the file. No checksum or encryption.
  `my_save_file.sav` is only a secondary buffer copy (`buffer_save_async` in async group `save_folder`, non-PC path); an earlier version of these notes
  wrongly treated it as the save.
- Sections (writer order is reversed in the file): `events` (001..250), `enemies` (001..120), `pantheon` (001..009), `mysteries` (80 flag names),
  `achievement` (147 keys: 121 `row,col` cells + plain `1`..`26`), `challenges` (1..15, reals), `translation` (`cut`, real), `city` (27 `r,c` reals plus
  copies of the option flags), `town` (`status` real; a run in progress adds `slot[..]`, `character[..]`, `board[..]`, `kyoto[..]`, ... and `fate`), `options`
  (settings, reals). Which keys are read vs written differs slightly (the loader skips the `city` cells inside `achievement`).
- **Unlock values are not `"yes"`.** `achievement_unlock(a, b)` and the event/enemy/mystery scripts store `"yes"` while a run is going. At the end of a
  run `endgame_check_achievements` rewrites each `"yes"` cell into **that cell's own 4-digit code** (`achiev[1][0] = "1980"`, `[1][1] = "9475"`, ...;
  the plain keys 1..26 likewise, several cells deliberately share a code) and `endgame_check_pantheon` turns `pantheon[1..5][0] == "yes"` into
  `478423 / 234645 / 195573 / 593821 / 555039`. The unlock checks compare against these codes (for example `omenu_front_Alarm_2` sets the
  `additional_pack` flags from `achiev[11][1]`, `[6][3]`, `[6][4]`, `[7][6]`, `[6][7]`, `[1][9]` and `townaction[4][1]` from `[1][2]`; character select,
  `options_achievements`, `roguelite_*`, `stat_079_whattounlocknext` do the same), so a save full of `"yes"` unlocks nothing. Events, enemies and
  mysteries are stored as plain `"yes"` (no code found in `event_init`, `endCheck_enemy`, `q001_janitor_END_Create_0`).
- `re/save_codes.json` is the cell -> code table, produced by `python -I re/scripts/achiev_codes.py <endgame_check_achievements .named.c> re/save_codes.json`
  (decompile `endgame_check_achievements` with `DecompBig.java`, ~5 min, then `slotnames.py`). The codes are literals in the exe: re-extract after an update.
- `python -I re/save_cheat.py [existing save.ito] <out>` keeps an existing file and sets achievement cells + pantheon 001..005 to their codes and
  events/enemies/mysteries to `"yes"`. Not touched (semantics not derived yet): `challenges`, `city`, `translation`, `options` unlock flags
  (`suitcase`, `cardpack`, `backpack`, `neighbor`, `controller`), pantheon 006..009.
- Debug code in the exe (`omenu_debug`): menu entries `all achievmt`, `allachiev`, `unlock first/second/third 24 achievements`; their handlers were not
  located yet and would show the game's own definition of "everything unlocked".
- Tools: `scripts/slotstrings.py` (global string slot -> literal; the initializer address is auto-detected), `slotnames.py` (annotates decompiled .c: string
  slots + builtin names), `annotasm.py` (same for `DumpAsm` text), `inicalls.py` (literal args of `ini_*` builtin calls without the decompiler; the
  native `ini_read_real`/`ini_write_real` calls are direct calls and not listed), `CodeSites.java` (index constants around a literal reference).
  Builtin calls are `call(self, other, &ret, argc, builtin_id_slot, args)`; a builtin id slot is 16 bytes in `.data` and its name pointer sits 8 bytes BEFORE it.
- Debug features: see `DEBUG.md` (activation, keys, debug tab, spawn console, line tester) and `debug_ids.tsv` (typed-ID tables). Tools: `scripts/datawin_names.py`
  (asset names/ids from `data.win`), `scripts/asmflow.py` + `scripts/annotasm.py` (readable disassembly for functions the decompiler cannot finish; 30 min is not enough
  for `newgod_debug` or the big draw events), `scripts/gml_summary.py`, `scripts/CodeSites.java`.
