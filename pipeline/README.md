# World of Horror: pipeline and reverse engineering notes

Target: `worldofhorror.exe` (PE32+ x64, GameMaker YYC build). Addresses, function names (`FUN_...`), md5s and counts change with every
build, so none are stored: the scripts find them again; addresses quoted below are examples from one build. Statements are observed
unless marked. The patched exe has not been run in the game: its behaviour is verified statically and by native tests only.

## The pipeline

`uv run woh.py <command>` (`woh.py --help` lists them; the script header declares Pillow) does three things, in order and only as needed:

1. **Reverse engineer** (`pipeline/reverse/`): headless Ghidra imports the installed exe, then scripts find patch sites, draw hooks,
   strings and the string value flow that `usage.tsv` needs. Variable slots and runtime helpers are found without Ghidra, directly from the exe.
2. **Generate artifacts** (`pipeline/generate/`): the hook binary, string target lists, save codes.
3. **Act** (`pipeline/act/`): patch the exe, write language files, replace sprites, write a save.

Game files are read from the Steam install (`--game DIR` for another library). Derived files live in the ignored
`build/<exe md5:8>-<data md5:8>/`, so a game update simply starts a new cache. Stages whose outputs exist are skipped, unless
a declared input (`translation/exe_strings.txt` for `targets`) is newer than them or a stage they need rewrote its
outputs with different contents in the same run: a source added to `exe_strings.txt` reruns `targets` and then `string-refs` (Ghidra).
`--force STAGE` reruns one, and is needed after editing a script, since script changes do not invalidate outputs. Actions always run.

`woh.py sync` writes the tracked translation files `translation/*.txt`. Run it after a game update. `translation/exe_strings.txt` is kept by hand:
sync only checks it against the build and writes the exe texts missing from it to `exe_strings_candidates.txt` in the build cache.
`hashes.txt` is the record of the game files the translation was made against: the sha256 of the exe, of each frame in `img/source` that has a PNG of the same name in `img/translation`, and of each font atlas (`font/<name>.png`) that has one in `img/translation/font` (the game's original pixels). `woh.py build` first checks the current files against it and refuses to write anything if one of them differs, listing the changed names (the game was updated: review those translations); a name not recorded yet is accepted, and after the outputs were written `build` adds the new names and drops those of deleted translations. `--no-exe` / `--no-sprites` leave the exe / the sprites and fonts out of both the check and the record. `woh.py hashes` is the only command that accepts changed files: it replaces the recorded hashes with the current ones. `woh.py check` compares the edited font atlases with the game's (`check/font_check.py`): same size, which characters' cells differ, and fails on changes outside every glyph cell.

**Building the translation:** `woh.py build` writes the language files, the patched exe and `data.win` (translated frames and font atlases) to `output/`
and does not touch the game folder; copy them in yourself. It also copies the changelog (the root file whose name ends with `СПИСОК ИЗМЕНЕНИЙ`) into `output/`; `--bundle` writes `<version>.zip` (standard deflate) in the root with the changelog, `THIRD-PARTY-NOTICE.md` (`cargo about`, needs `cargo-about` installed; config in `installer/about.toml`, `about.hbs`) and `wohrus`, the installer: `installer/` is built with cargo, and a pack of bsdiff patches against the game files plus the other `output/` files is appended to it; the version being the text before the first space of the changelog's name. The installer's cargo profile and target are set with `--profile` (default `win-msvc-release`) and `--target` (default: the host), e.g. `--profile win-clang-release --target x86_64-pc-windows-gnullvm`. Files this pipeline wrote are recorded in `build/produced.md5` and refused as
input, as is any exe with our sections. To build again after installing, run Steam's "Verify integrity of game files".

### Setup

Set `GHIDRA_HEADLESS` (path of `analyzeHeadless`), `WOH_GHIDRA_JAVA` (`JAVA_HOME` for Ghidra, if needed) and `UTMT_CLI`
(UndertaleModCli). Clang and uv are taken from PATH. `woh.py` sets `GHIDRA_HEADLESS_MAXMEM=6G`, since the 2 GB default runs out of
memory, and `FastAnalysis.java` switches off analyzers that are not needed, more than halving analysis time. Native hook tests
(`pipeline/check/test_hook.py`, `check_patched.py`, `image_check.py`) need Windows and report as skipped elsewhere.

If `FindPatchSites` throws, the draw events changed shape. If `resolve_helpers.py` stops, the helper it names no longer matches its rule,
and the rule needs changing. Either way, read the log the error points to.

## How GML string literals are stored

- Each literal is a NUL-terminated UTF-8 blob in `.rdata`.
- Per-script static initializers run at startup: a string-object constructor is called with `(&slot, "text")`, followed by an atexit
  registration. The constructor allocates a 16-byte string object `{ char* ptr; ...; uint len = strlen(ptr) | 0x80000000; refcount = 1 }`
  and stores it in a global `slot` (16-byte value, tag 1 = string).
- Length is computed by a runtime strlen, so **a replacement string can be any length**. Only the pointer must reach it. The size limit
  of in-place hex editing belongs to the editing method, not to the engine.
- Literals are not deduplicated across scripts: a text has several copies (e.g. `STA`, `REA`, `ALL`), each owned by one script's
  initializer.
- A string copy can directly follow a binary constant, so a byte scan for NUL-preceded text misses it. Find copies through code
  references, not through byte patterns.
- Builtin calls look like `call(self, other, &ret, argc, builtin_id_slot, args)`; a builtin id slot is 16 bytes in `.data` and its
  name pointer sits 8 bytes BEFORE it. A variable slot has the same layout.
- Runtime helpers (names differ per build): value comparison (0 = equal), array indexing, value assign, number multiply/add, `+=`,
  call-by-index wrapper, debug print.

## STA / REA / ALL in battle

Battle damage type is a string value: `"STA"` / `"REA"` / `"ALL"` (also `"DOOM"`, `"stamina damage"`, `"injury"`, `"curse"`).
The `.jn` entries `STA|STA` / `REA|REA` (`woh_dec.jn`) are used only on the character status screen.

Producers (assign the literal as an argument/value):

- `gml_Script_customenemy_init`: builds each custom enemy attack with a 3-argument script call whose third argument is the type literal.
- `gml_Object_nenm_xxx_*` and other enemy definition scripts.

Consumers (read the slot and compare it):

- `gml_Script_newcombat_penalty`: game logic. Compares the penalty type with `STA`, `stamina damage`, `REA`, `ALL`, `DOOM`, `injury`,
  `curse` and applies the effect. **These comparisons must keep matching the producers.**
- `gml_Object_parent_newcombat_Draw_0`, `gml_Object_nenm_xxx_custom_Draw_0`, `gml_Object_nenm_xxx_custom_ext_Draw_0`: drawing code.

Editing a shared literal breaks logic, because the English path draws the key itself (label = type). Changing only some copies makes
producers and `newcombat_penalty` disagree (probable cause of broken battles after hex edits of `REA`; unconfirmed).

### The `lang == 7` label block in the draw events

- The exe stores per-language labels next to the keys, e.g. `DOOM`/`ZGŁ`, `STA`/`KND`, `REA`/`RZS`, `ALL`/`WSZ`, then `VDBN`, `AUS`, `VNF`.
- Each of the three draw events has exactly one `if (lang == 7.0)` block (about 3 KB) covering the `DOOM`/`STA`/`REA`/`ALL` slots. It
  contains only compares and label assignments; `label = type` happens before it, so the English path draws the raw type. Other
  branches (`lang == 1..6`) hold labels for other languages.
- The language is a local read from a global variable and compared with double constants 1..7 (`7.0` = `MOV RAX,0x401c000000000000`).
- Inference, not proven by running the game: that global is the language index. The `.jn` loader reads the same variable; the constants
  follow the exe's language table order (`eng, jap, cht, chs, kor, fra, ger, pol, ukr, tur`), 7 = pol, and the labels are Polish
  abbreviations.
- Sites (guard `0F 85 rel32` per event, twelve `LEA RDX,[rip+disp32]` label loads) are in `patch_sites.tsv`.

## Patching

`woh.py build` (reads the generated `patch_sites.tsv`; output goes to `output/`, the input is never overwritten):

1. NOPs the three `lang == 7` guards so the label block runs for every language.
2. Repoints the label loads at UTF-8 text in a new `.ruloc` section. The text comes from the first four lines of `translation/exe_strings.txt`
   (`DOOM`, `STA`, `REA`, `ALL`). An empty entry keeps its English key as the label; if all four are empty the guards and loads are
   left alone. Any length works.
3. Translated hardcoded strings go through the draw-time hook (below), added to the same output. Entries marked `!` additionally
   have the exe's own copies repointed (see next section).

Logic literals are untouched. The PE has no signature or overlay and enough header slack to append a section. The block was judged
label-only from disassembly.

## Translating hardcoded strings

- `targets.tsv`: candidate strings and all their copies (VA, escaped text), built by `make_targets.py` from
  `ExportPoolStrings.java` (every code-referenced string). Selection: the sources already in `translation/exe_strings.txt`, plus short ALL-CAPS
  tokens (`PREP`, `S.ATK`, `MAGIC`, ...) and quoted ALL-CAPS names (`'HAPPY LEMON'`), and multi-word English text (`Logging in... DONE`, `current weather: `; no `_`, `[`, `gml_` or backslash), excluding the damage-type keys and label strings
  `patch.py` handles.
- `refs.tsv`: every code reference to those copies, from `ExportStringRefs.java`. Only RIP-relative `lea` is used; `mov` entries
  are Ghidra value propagation and are ignored. Texts without a `lea` reference (the two-letter `MC`..`CC` codes, odd fragments) can
  not be changed by `patch.py`, which warns if one is translated.
- `translation/exe_strings.txt`: the document, `source|translation`, kept by hand (format and escapes: README.md, "Как заполнять
  `exe_strings.txt`"). `woh.py sync` never changes it: it writes the targets missing from it to `out/exe_strings_candidates.txt` in the
  build cache and lists document entries without a code copy in this build.
- A leading `!` marks an entry for literal replacement: `patch.py` repoints every copy's loads at the translation in `.ruloc`. It is for
  text modified before drawing, at the cost of the logic guarantee; the patch stops before changing anything if a marked text is `logic`
  in `usage.tsv`. Unmarked entries are hook-only.
- Being in the document does not make a string safe to translate: some are logic keys (`SVR KICK`, `ALLY ATK`, `NO CASH`) compared
  against values created elsewhere.

### Will a translation change behaviour?

- No code reference lands inside a target string (`StringUses.java`, `interior`): replacing a string start moves every reference to it.
- Usage classes (`StringUses.java` + `classify_usage.py` -> `usage.tsv`; the rules are in the `classify_usage.py` header): `logic` means
  the code compares the text, found by a compare helper call soon after the load (e.g. `SVR KICK`, `ALLY ATK`, `PREP`), a variable name
  built from the text (`status_` + `fearful`: replacing `fearful` left `status_fearful` unset and every battle failed in `newcombat_init`
  with "Cannot compare unset variables"; `iktyosis` and `nails` too), or a string `switch` case table (`draw_script_event_location`:
  `forest`, ..., `yumiko`). `rolled` is not `logic`: it is loaded before the `language == 1..9` checks but never compared. It is built
  into a longer text by concatenation (`[` + `rolled` + `: ` + ...), so only a `!` mark can translate it; the draw-time hook never sees it whole.
- `PREP` etc. are action IDs: `combat_loadactions` / `combat_clickactions` build arrays like `["PREP", 20*i, 40*j]`, `combat_action`
  compares the ID, and the same string is the button text. Text and key are one value.
- Replacing every copy keeps comparisons between values that both originate from exe literals equal. It does not guarantee: a value
  persisted (save file, ini) and read back after the patch; a string used for content-dependent work (length, characters, building
  asset/variable names); a counterpart that lives in `data.win`.
- A real guarantee needs the logic values left untouched and the text swapped only at draw time: the hook below.

## Draw-time translation hook

Logic values are never changed; the text argument of the text-drawing built-ins is swapped for the duration of the call.

- **Where:** the runtime registers every built-in with `register(name, function, argc, flag)`, the function loaded by `LEA RDX,[rip+d]`
  (`FindDrawHooks.java` -> `draw_hooks.tsv`). Hooked: `draw_text*` (text = argument 2) and `string_width/height[_ext]` (argument 0).
  Each implementation is referenced only by this `lea` and its `.pdata` record, so every call goes through the registered pointer.
  Calls come through the call-by-index wrapper, which copies the arguments into a private array on its stack and passes it as the
  fifth argument.
- **Runtime layout:** RValue = {value @0, flags @8, kind @0xc (low 24 bits)}; kind 1 = string; value -> RefString {char\* @0,
  refcount @8, size @0xc}; the game's own constants use refcount 1 and size = length|0x80000000.
- **Hook** (`pipeline/generate/hook/hook.s`): a stub `lea r10,[info]; jmp common` per site; `common` checks argc > index and kind == string, FNV-1a
  hashes the text, probes the table, on a hit stores the translation's address into a static RefString and puts that in the argument
  slot, calls the original, then restores the original value pointer. No absolute addresses (the table holds offsets, the translation
  address is stored at hit time), so no relocations are needed. An unwind entry (`UNWIND_ALLOC_0x48`) is appended to `.pdata` so
  exceptions can pass through.
- **Layout of the patched exe:** `.ruloc` (RW: label text, table, strings, unwind info) then `.ruhook` (RX: hook,
  stubs, infos).
- **Tests:** `pipeline/check/test_hook.py` runs the real hook against a fake built-in (hits, misses, collisions, control characters,
  non-strings, argc too small, restore, stack alignment). `check_patched.py` runs the patched exe's
  own stubs/table/code for every hooked built-in and checks the `.pdata` entry (needs clang tools on PATH). `image_check.py` asks
  the Windows loader (`CreateFileMapping` with `SEC_IMAGE`, no execution) whether the file is a valid image; error 193 = malformed PE.
  `woh.py` builds the hook with clang.
- **Limits:** only a string passed WHOLE to one of the hooked built-ins is translated (text built by concatenation or changed by a script
  before drawing is not); a translation longer than the original may overflow a layout; `string_width` of a translated text is measured
  on the translation (good), but code that measures the original and draws with the hook sees different widths.

## Sprites in `data.win`

- `data.win` ships with a YYC build: YYC only replaces the GML bytecode (no `CODE`/`VARI`/`FUNC` chunks). Sprites, textures, audio,
  fonts, object and room definitions still live in `data.win`; the exe has none of the image data. Assets are referenced by **index**
  (`SPRT` order), never by name, so a name grep finds nothing.
- The game never calls the registered `draw_sprite*` built-in implementations. YYC calls native helpers directly with the sprite id in
  `EDX`, so a hook on those built-ins sees almost nothing.

## Not scanned

Strings under 2 characters, UTF-16 text, mixed-case single words (almost all keyboard-mash cheat sequences), identifiers and debug tags
(`_`, `[`, `gml_`) and `data.win`. The rules in `make_targets.py` (ALL-CAPS tokens, multi-word English text) are the only ones that add
texts to the candidates report.

## Save file (format confirmed against a real game-written `save.ito`; unlocks NOT yet confirmed in the game)

- The save is the plain-text INI `%LOCALAPPDATA%\wohgame\save.ito` (GameMaker save area; GEN8 name `wohgame`), CRLF, `key="value"`
  (reals are written quoted, e.g. `"0.000000"`). `scr_systemload` calls `scr_openini("save.ito")` (= `ini_open`) on PC and reads every
  key directly into globals (`achiev[r][c] = ini_read_string("achievement", "r,c", "")`, reals via `ini_read_real`).
  `scr_systemsave` writes the same keys with `ini_write_string` / `ini_write_real`; `ini_close` writes the file. No checksum or
  encryption. `my_save_file.sav` is only a secondary buffer copy (non-PC path), not the save.
- Sections (writer order is reversed in the file): `events` (001..250), `enemies` (001..120), `pantheon` (001..009), `mysteries` (80 flag
  names), `achievement` (147 keys: 121 `row,col` cells + plain `1`..`26`), `challenges` (1..15, reals), `translation` (`cut`, real), `city`
  (27 `r,c` reals plus copies of the option flags), `town` (`status` real; a run in progress adds `slot[..]`, `character[..]`,
  `board[..]`, `kyoto[..]`, ... and `fate`), `options` (settings, reals). Which keys are read vs written differs slightly (the loader
  skips the `city` cells inside `achievement`).
- **Unlock values are not `"yes"`.** `achievement_unlock(a, b)` and the event/enemy/mystery scripts store `"yes"` while a run is going.
  At the end of a run `endgame_check_achievements` rewrites each `"yes"` cell into **that cell's own 4-digit code** (`achiev[1][0] =
"1980"`, `[1][1] = "9475"`, ...; the plain keys 1..26 likewise, several cells deliberately share a code) and
  `endgame_check_pantheon` turns `pantheon[1..5][0] == "yes"` into `478423 / 234645 / 195573 / 593821 / 555039`. The unlock checks
  compare against these codes (for example `omenu_front_Alarm_2` sets the `additional_pack` flags from `achiev[11][1]`, `[6][3]`,
  `[6][4]`, `[7][6]`, `[6][7]`, `[1][9]` and `townaction[4][1]` from `[1][2]`; character select, `options_achievements`,
  `roguelite_*`, `stat_079_whattounlocknext` do the same), so a save full of `"yes"` unlocks nothing. Events, enemies and mysteries
  are stored as plain `"yes"`.
- `out/save_keys.json` holds the mystery and enemy keys (`inicalls.py` on `scr_systemsave`) and the pantheon codes; the `[events]` count is
  a constant in `save_cheat.py`, because its keys are built in a loop.
- `out/save_codes.json` is the cell -> code table, generated by the `save-codes` stage (decompiles `endgame_check_achievements` with
  `DecompBig.java`, ~5 min, then `slotnames.py` and `achiev_codes.py`).
- `woh.py save [existing save.ito] <out>` keeps an existing file and sets achievement cells + pantheon 001..005 to their
  codes and events/enemies/mysteries to `"yes"`. Not touched (semantics not derived): `challenges`, `city`, `translation`, `options`
  unlock flags (`suitcase`, `cardpack`, `backpack`, `neighbor`, `controller`), pantheon 006..009.
- `omenu_debug` has entries `all achievmt` and `allachiev`; their handlers were not located (see "Debug features").

## Debug features

Everything here comes from the game's own code (Ghidra decompile/disassembly of `worldofhorror.exe`) and `data.win`, not from running
the game. Each entry carries a confidence tag:

- **[code]** the condition and the effect are read directly from the code.
- **[names]** the effect is inferred from variable and asset names; the mechanism is certain, the exact gameplay result is not.
- **[open]** the code exists but its trigger or effect was not decoded.

Keys are Windows virtual-key codes in the game; letters are the usual keys, `Num0`..`Num9` the numeric keypad.

### 1. Turning debug mode on and off

Everything below except section 2.3 does nothing while the global `debug` flag is 0, and it starts at 0 on every launch.

| Where                    | Keys                 | Effect                                                                                                                           |
| ------------------------ | -------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Main menu (title screen) | **Ctrl + Shift + H** | Toggles `debug` and GameMaker's runtime debug overlay (`show_debug_overlay`). Plays the sound `nes_woof` as feedback. **[code]** |

So: start the game, stay on the title screen, press Ctrl+Shift+H, listen for the woof. Press it again to switch off.

### 2. Main menu tools

#### 2.1 Frame-rate display, `I` **[code]**

With `debug` on, `I` toggles `fpscheck` (an FPS readout on the title screen).

#### 2.2 Translation line tester, `U` **[code for controls, names for the file list]**

With `debug` on, `U` toggles `testing_lines`. The title screen then shows a line browser that walks through the game's language
tables, one line at a time, with the text `[PRESS 'U' TO LEAVE] [RIGHT SIDE]: Language: 1 / Line break: 1` and a CJK width-test string.
This is the only built-in way to see every translated line without playing to it, so it is the most useful tool for this project.

| Key                      | Effect                                                                                  |
| ------------------------ | --------------------------------------------------------------------------------------- |
| Left / Right             | Previous / next language file (`testLine_file`, file 1 upwards; Right stops near 20-21) |
| Up / Down                | Next / previous line (`testLine_id`) by 1                                               |
| Shift + Up / Down        | by 10                                                                                   |
| Ctrl + Shift + Up / Down | by 100                                                                                  |
| F2                       | Language of the right-hand side (shown as `(F2) Language: n`)                           |
| F3                       | Line-break mode (shown as `(F3) Line break: n`)                                         |
| U                        | Leave                                                                                   |

The file numbers map to these tables (the short names are what the game uses on screen, they match the `woh_*.jn` files):
1 add, 2 hal, 3 chl, 4 cha, 5 cbt, 6 enm, 7 evt, 8 go, 9 home, 10 ichi, 11 mys, 12 ni, 13 palette, 14 perk, 15 san, 16 small,
17 spell, 18 ui, 19 shichi, 20 roku, 21 nana, 22 hachi. `woh_dec`, `woh_mod`, `woh_ver` and `woh_yon` are not in the list, so
this tester cannot show them. Whether Right can reach 22 was not decoded.

#### 2.3 Mod debugging, `Ctrl + N` (works without `debug`) **[code]**

Toggles `modding_debug` and plays `nes_woof`. With it on, custom events and custom enemies (the `evt_xxx_custom*` and `nenm_xxx_custom*`
objects that load from `extra content`) answer `N` by toggling their `debug_view` overlay. Only relevant when testing mods.

#### 2.4 Version switch, `V` **[open]**

The title screen draws "Press V to switch between 1.22 and 1.25." and `V` toggles it, but only under a condition that was not decoded
(probably the `update125` build flag). Probably dead in the current release.

### 3. Keys that work on every screen (debug on) **[code]**

| Key                     | Effect                                                                                                                                                                            |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `5` (main keyboard row) | Prints `can load?: <can_load>` to the debug log                                                                                                                                   |
| **F2**                  | Sets `language` to 0 if it is 1, otherwise to 1 (0 = English, 1 = Japanese in the exe's language table), prints `language: n`, and runs a refresh over the objects that hold text |
| F3                      | Toggles `short_ini` 0/1 (it is the value saved as `[translation] cut`) and prints `[debug]: current cut = n`                                                                      |
| F4                      | Cycles `screen_scale` 1 -> 2 -> 3 -> 1 and re-applies the window size                                                                                                             |
| F5                      | Toggles `show_jp_combat` (Japanese text in combat)                                                                                                                                |

The debug log goes to the GameMaker debug output / overlay, not to the screen.

### 4. During a run

#### 4.1 The Debug tab **[code for the buttons, names for the gameplay effect]**

While `debug` is on, **right mouse button** on the run screen (`o_newgod`) switches its tab to `debug`. The tab shows a menu headed
`DEBUG MENU` and these buttons (click to use):

| Button                        | Effect                                                                                                                                            |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| unlock first 24 achievements  | sets `achiev[r][c] = "yes"` for rows 1-3, columns 0-8 (27 cells)                                                                                  |
| unlock second 24 achievements | rows 4-6, columns 0-8                                                                                                                             |
| unlock third 24 achievements  | rows 7-9, columns 0-8                                                                                                                             |
| +100 EXPERIENCE               | experience += 100                                                                                                                                 |
| +3 / -3 STAMINA               | body +3 / -3                                                                                                                                      |
| +3 / -3 REASON                | sanity +3 / -3                                                                                                                                    |
| +5% / -5% DOOM                | doom +5 / -5                                                                                                                                      |
| force three new mysteries     | sets the forced-mystery debug flag; the game prints `[debug]: reroll on mystery board screen to activate`, so reroll the mystery board afterwards |
| 1.2.2 List new items          | prints the items added in 1.2.2                                                                                                                   |
| 1.2.2 List new status cards   | prints the status cards added in 1.2.2                                                                                                            |
| All stats to 12               | all stats set to 12                                                                                                                               |
| All stats to 1                | all stats set to 1                                                                                                                                |
| Give good ending              | creates the `ending_good` object (ends the run with the good ending)                                                                              |
| Give stamina ending           | creates the `ending_stamina` object                                                                                                               |

A footer says `[DEBUG] quit to save changes`. The achievement buttons write the in-run marker `"yes"`; the game converts it into the per-cell
codes in `endgame_check_achievements` when a run ends, which is also what makes it persist in `save.ito` (see "Save file" above).
So after pressing them, finish the run (for example with "Give good ending") instead of just closing the game.

#### 4.2 Numpad spawn console (works on any run screen, not only the tab) **[code]**

Press a numpad key to arm a mode, type a three-digit ID (the digits of the asset name, for example `191` for `itm_191_hitomisjacket`),
then press the same numpad key again to confirm. The valid IDs are the `NNN` of the `data.win` object names of each kind (`itm_NNN_*`, `evt_NNN_*`, ...).

| Numpad | Mode            | IDs (count)      | What it creates                                                                                                                                     |
| ------ | --------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0      | item            | `itm_NNN` (195)  | an item card (`You've got a new item card: ...`)                                                                                                    |
| 1      | status          | `stat_NNN` (79)  | a status card                                                                                                                                       |
| 2      | event / command | `evt_NNN` (250)  | that event; also the words `kill` (closes all open events) and `chara` (spawns the allies `fol_033_kimura`, `fol_032_aoshima`, `fol_034_rescuedog`) |
| 4      | perk            | `upg_NNN` (76)   | a perk card                                                                                                                                         |
| 5      | enemy           | `nenm_NNN` (116) | that enemy (starts the fight)                                                                                                                       |
| 9      | spell           | `spl_NNN` (38)   | a spell card                                                                                                                                        |

`V` closes an event, destroys a combat object, or advances the endless map (see 4.4) **[code for what each call is, names for the result]**.

#### 4.3 Held-`B` shortcuts **[code]**

While holding **B** on the run screen:

| Second key | Effect                                                    |
| ---------- | --------------------------------------------------------- |
| E          | stamina +3 and reason +3                                  |
| R          | stamina set to 0 (tests the stamina ending)               |
| A          | doom set to 99                                            |
| J          | `status_meme` set to 5                                    |
| K          | creates the otherworld event (`evt_xxx_otherworld`)       |
| S          | creates the card `card_eyescene_OLD`                      |
| I          | creates the village shop card (`card_action_villageshop`) |

#### 4.4 Other debug keys on specific screens **[code]**

| Screen                 | Key                 | Effect                                                                                                                                                                                                                              |
| ---------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Event card             | right mouse button  | closes the event                                                                                                                                                                                                                    |
| Perk card              | middle mouse button | removes the perk card                                                                                                                                                                                                               |
| Event / combat         | `V`                 | closes the event / destroys the combat object                                                                                                                                                                                       |
| Endless map            | `V`                 | `endless_progress += 8`                                                                                                                                                                                                             |
| Clothes card           | right mouse button  | forces the clothes card forward (`progress_character`) **[names]**                                                                                                                                                                  |
| Town map               | `Ctrl`+`U`          | doom = 0                                                                                                                                                                                                                            |
| Town map               | `Ctrl`+`O`          | `stat_doomcheck` = 0                                                                                                                                                                                                                |
| Town map               | `Ctrl`+`I`          | prints `[debug]: my timeline <n>`                                                                                                                                                                                                   |
| Town map               | arrows              | Left spawns an `o_creep`; Up creates a perk card and a spell; Right sets the Vigil pamphlet quest (`q18*`) flags; Down puts mysteries 18-21 into the mystery slots **[names]**                                                      |
| Mystery board          | right mouse button  | prints `[debug]: lockedslot[0]` / `[1]` (the locked mystery slots)                                                                                                                                                                  |
| Home card              | `Alt`               | prints the chosen mystery, endless-mode state and target platform                                                                                                                                                                   |
| Quest 007 map          | `Enter` / `Ctrl`    | mystery timer = 8 and timeline = 1 / timeline = 1                                                                                                                                                                                   |
| Quest 008 map          | `D`                 | cycles the `weather` value 0..5                                                                                                                                                                                                     |
| Quest 017 map          | `Ctrl`              | `path` = 0                                                                                                                                                                                                                          |
| Quest 020              | Down                | closes the boss prelude object                                                                                                                                                                                                      |
| Tarot deck item        | Space               | doom = 91 and experience = 100                                                                                                                                                                                                      |
| Dream devourer         | `M` / `N`           | prints the story-fight state and clears four flags / sets enemy health to 0                                                                                                                                                         |
| Shiro the gardener     | `U`                 | spawns an effect and sets a flag                                                                                                                                                                                                    |
| Forest-fear card       | `B` / `M` / `N`     | adds three items (`itm_191_hitomisjacket`, `itm_190_junpeisnotebook`, `itm_188_boltcutter`) and prints `[debug] items added!` / toggles the card visible and creates the event `evt_231_thehouse` / creates `itm_192_twinseffigies` |
| Combat, ritual style 3 | (automatic)         | text overlay with the ritual arrays, `patient_killed` and `extra_damage`                                                                                                                                                            |

### 5. Things that cannot be switched on

- `omenu_debug` (a panel on the title screen with `debug: on/off`, `paxdemo`, `intro`, `wolf's font`, `force mystery 1-5 / 6-10`,
  `clear achievmt`, `all achievmt`, `noachiev`, `allachiev`, ...) only draws when `god_debug` is 1. No code in the exe ever sets
  `god_debug` to 1, so it is dead code in this build.
- The title-screen buttons `goddebug`, `paxdebug`, `introdebug`, `eventedit`, `pax1start`, `pax2start`, `paxextra`, `myst15`, `myst610`
  are gated by the same flags and are likewise not reachable.
- `paxdemo`, `goddebug_intro`, `goddebug_mystery`, `ouren_test`, `level_editor`, `update125` are read in many places (demo and debug
  variants of title, cards, mystery logic); how to set them from the UI was not found. **[open]**

### 6. Using it for translation work

1. Title screen: Ctrl+Shift+H, then `U`: walk the language files line by line, F3 for the line-break mode, F2 to compare with another language.
2. Ctrl+Shift+H, then F2: flip language 0/1 live while a screen is open; F5 for Japanese combat text.
3. In a run: numpad 2 + `NNN` to open any event card (the ID is the `NNN` of `evt_NNN_*`, and `woh_event.jn` has the text), numpad 5 + `NNN` for any enemy,
   numpad 0 for items, numpad 1 for status cards, numpad 4 for perks, numpad 9 for spells. This is the fastest way to see a given piece of text in context.
4. Unlock everything for testing: `save_cheat.py` (see "Save file" above), or the three unlock buttons plus "Give good ending".

### 7. Where the code is (for re-checking after a game update)

- Debug flag and key handlers: `gml_Object_omenu_front_KeyPress_72/73/78/85`, `gml_Object_overload_KeyPress_53/113/114/115/116`,
  `gml_Object_o_newgod_Mouse_5`, `gml_Object_o_newgod_Keyboard_66`, `gml_Object_o_newgod_Step_0` -> `gml_Script_newgod_debug` (numpad
  console), `gml_Object_o_newgod_Draw_0` (debug tab), `gml_Object_omenu_front_Draw_0` (line tester). Addresses change per build.
- The huge draw events and `newgod_debug` do not decompile in reasonable time.
