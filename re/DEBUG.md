# World of Horror: debug features manual

Everything here comes from the game's own code (Ghidra decompile/disassembly of `worldofhorror.exe`, build seen 2026-10-31) and `data.win`.
**None of it has been run in the game**, because the analysis had no view of the screen. Each entry carries a confidence tag:

- **[code]** the condition and the effect are read directly from the code.
- **[names]** the effect is inferred from variable and asset names; the mechanism is certain, the exact gameplay result is not.
- **[open]** the code exists but its trigger or effect was not decoded.

Keys are Windows virtual-key codes in the game; letters are the usual keys, `Num0`..`Num9` the numeric keypad.

## 1. Turning debug mode on and off

Everything below except section 2.3 does nothing while the global `debug` flag is 0, and it starts at 0 on every launch.

| Where | Keys | Effect |
|---|---|---|
| Main menu (title screen) | **Ctrl + Shift + H** | Toggles `debug` and GameMaker's runtime debug overlay (`show_debug_overlay`). Plays the sound `nes_woof` as feedback. **[code]** |

So: start the game, stay on the title screen, press Ctrl+Shift+H, listen for the woof. Press it again to switch off.

## 2. Main menu tools

### 2.1 Frame-rate display, `I` **[code]**
With `debug` on, `I` toggles `fpscheck` (an FPS readout on the title screen).

### 2.2 Translation line tester, `U` **[code for controls, names for the file list]**
With `debug` on, `U` toggles `testing_lines`. The title screen then shows a line browser that walks through the game's language
tables, one line at a time, with the text `[PRESS 'U' TO LEAVE] [RIGHT SIDE]: Language: 1 / Line break: 1` and a CJK width-test string.
This is the only built-in way to see every translated line without playing to it, so it is the most useful tool for this project.

| Key | Effect |
|---|---|
| Left / Right | Previous / next language file (`testLine_file`, file 1 upwards; Right stops near 20-21) |
| Up / Down | Next / previous line (`testLine_id`) by 1 |
| Shift + Up / Down | by 10 |
| Ctrl + Shift + Up / Down | by 100 |
| F2 | Language of the right-hand side (shown as `(F2) Language: n`) |
| F3 | Line-break mode (shown as `(F3) Line break: n`) |
| U | Leave |

The file numbers map to these tables (the short names are what the game uses on screen, they match the `woh_*.jn` files):
1 add, 2 hal, 3 chl, 4 cha, 5 cbt, 6 enm, 7 evt, 8 go, 9 home, 10 ichi, 11 mys, 12 ni, 13 palette, 14 perk, 15 san, 16 small,
17 spell, 18 ui, 19 shichi, 20 roku, 21 nana, 22 hachi. `woh_dec`, `woh_mod`, `woh_ver` and `woh_yon` are not in the list, so
this tester cannot show them. Whether Right can reach 22 was not decoded.

### 2.3 Mod debugging, `Ctrl + N` (works without `debug`) **[code]**
Toggles `modding_debug` and plays `nes_woof`. With it on, custom events and custom enemies (the `evt_xxx_custom*` and `nenm_xxx_custom*`
objects that load from `extra content`) answer `N` by toggling their `debug_view` overlay. Only relevant when testing mods.

### 2.4 Version switch, `V` **[open]**
The title screen draws "Press V to switch between 1.22 and 1.25." and `V` toggles it, but only under a condition that was not decoded
(probably the `update125` build flag). Probably dead in the current release.

## 3. Keys that work on every screen (debug on) **[code]**

| Key | Effect |
|---|---|
| `5` (main keyboard row) | Prints `can load?: <can_load>` to the debug log |
| **F2** | Sets `language` to 0 if it is 1, otherwise to 1 (0 = English, 1 = Japanese in the exe's language table), prints `language: n`, and runs a refresh over the objects that hold text |
| F3 | Toggles `short_ini` 0/1 (it is the value saved as `[translation] cut`) and prints `[debug]: current cut = n` |
| F4 | Cycles `screen_scale` 1 -> 2 -> 3 -> 1 and re-applies the window size |
| F5 | Toggles `show_jp_combat` (Japanese text in combat) |

The debug log goes to the GameMaker debug output / overlay, not to the screen.

## 4. During a run

### 4.1 The Debug tab **[code for the buttons, names for the gameplay effect]**
While `debug` is on, **right mouse button** on the run screen (`o_newgod`) switches its tab to `debug`. The tab shows a menu headed
`DEBUG MENU` and these buttons (click to use):

| Button | Effect |
|---|---|
| unlock first 24 achievements | sets `achiev[r][c] = "yes"` for rows 1-3, columns 0-8 (27 cells) |
| unlock second 24 achievements | rows 4-6, columns 0-8 |
| unlock third 24 achievements | rows 7-9, columns 0-8 |
| +100 EXPERIENCE | experience += 100 |
| +3 / -3 STAMINA | body +3 / -3 |
| +3 / -3 REASON | sanity +3 / -3 |
| +5% / -5% DOOM | doom +5 / -5 |
| force three new mysteries | sets the forced-mystery debug flag; the game prints `[debug]: reroll on mystery board screen to activate`, so reroll the mystery board afterwards |
| 1.2.2 List new items | prints the items added in 1.2.2 |
| 1.2.2 List new status cards | prints the status cards added in 1.2.2 |
| All stats to 12 | all stats set to 12 |
| All stats to 1 | all stats set to 1 |
| Give good ending | creates the `ending_good` object (ends the run with the good ending) |
| Give stamina ending | creates the `ending_stamina` object |

A footer says `[DEBUG] quit to save changes`. The achievement buttons write the in-run marker `"yes"`; the game converts it into the per-cell
codes in `endgame_check_achievements` when a run ends, which is also what makes it persist in `save.ito` (see `NOTES.md`, "Save file").
So after pressing them, finish the run (for example with "Give good ending") instead of just closing the game.

### 4.2 Numpad spawn console (works on any run screen, not only the tab) **[code]**
Press a numpad key to arm a mode, type a three-digit ID (the digits of the asset name, for example `191` for `itm_191_hitomisjacket`),
then press the same numpad key again to confirm. The valid IDs are in `re/debug_ids.tsv` (columns `kind`, `id`, `asset`).

| Numpad | Mode | IDs (count) | What it creates |
|---|---|---|---|
| 0 | item | `itm_NNN` (195) | an item card (`You've got a new item card: ...`) |
| 1 | status | `stat_NNN` (79) | a status card |
| 2 | event / command | `evt_NNN` (250) | that event; also the words `kill` (closes all open events) and `chara` (spawns the allies `fol_033_kimura`, `fol_032_aoshima`, `fol_034_rescuedog`) |
| 4 | perk | `upg_NNN` (76) | a perk card |
| 5 | enemy | `nenm_NNN` (116) | that enemy (starts the fight) |
| 9 | spell | `spl_NNN` (38) | a spell card |

`V` closes an event (and the `V` keys on the combat and endless-map screens do the following: an event closes, a combat object is
destroyed, the endless map advances 8 steps) **[code for what each call is, names for the result]**.

### 4.3 Held-`B` shortcuts **[code]**
While holding **B** on the run screen:

| Second key | Effect |
|---|---|
| E | stamina +3 and reason +3 |
| R | stamina set to 0 (tests the stamina ending) |
| A | doom set to 99 |
| J | `status_meme` set to 5 |
| K | creates the otherworld event (`evt_xxx_otherworld`) |
| S | creates the card `card_eyescene_OLD` |
| I | creates the village shop card (`card_action_villageshop`) |

### 4.4 Other debug keys on specific screens **[code]**
| Screen | Key | Effect |
|---|---|---|
| Event card | right mouse button | closes the event |
| Perk card | middle mouse button | removes the perk card |
| Event / combat | `V` | closes the event / destroys the combat object |
| Endless map | `V` | `endless_progress += 8` |
| Clothes card | right mouse button | forces the clothes card forward (`progress_character`) **[names]** |
| Town map | `Ctrl`+`U` | doom = 0 |
| Town map | `Ctrl`+`O` | `stat_doomcheck` = 0 |
| Town map | `Ctrl`+`I` | prints `[debug]: my timeline <n>` |
| Town map | arrows | Left spawns an `o_creep`; Up creates a perk card and a spell; Right sets the Vigil pamphlet quest (`q18*`) flags; Down puts mysteries 18-21 into the mystery slots **[names]** |
| Mystery board | right mouse button | prints `[debug]: lockedslot[0]` / `[1]` (the locked mystery slots) |
| Home card | `Alt` | prints the chosen mystery, endless-mode state and target platform |
| Quest 007 map | `Enter` / `Ctrl` | mystery timer = 8 and timeline = 1 / timeline = 1 |
| Quest 008 map | `D` | cycles the `weather` value 0..5 |
| Quest 017 map | `Ctrl` | `path` = 0 |
| Quest 020 | Down | closes the boss prelude object |
| Tarot deck item | Space | doom = 91 and experience = 100 |
| Dream devourer | `M` / `N` | prints the story-fight state and clears four flags / sets enemy health to 0 |
| Shiro the gardener | `U` | spawns an effect and sets a flag |
| Forest-fear card | `B` / `M` / `N` | adds three items (`itm_191_hitomisjacket`, `itm_190_junpeisnotebook`, `itm_188_boltcutter`) and prints `[debug] items added!` / toggles the card visible and creates the event `evt_231_thehouse` / creates `itm_192_twinseffigies` |
| Combat, ritual style 3 | (automatic) | text overlay with the ritual arrays, `patient_killed` and `extra_damage` |

## 5. Things that cannot be switched on

- `omenu_debug` (a panel on the title screen with `debug: on/off`, `paxdemo`, `intro`, `wolf's font`, `force mystery 1-5 / 6-10`,
  `clear achievmt`, `all achievmt`, `noachiev`, `allachiev`, ...) only draws when `god_debug` is 1. No code in the exe ever sets
  `god_debug` to 1, so it is dead code in this build.
- The title-screen buttons `goddebug`, `paxdebug`, `introdebug`, `eventedit`, `pax1start`, `pax2start`, `paxextra`, `myst15`, `myst610`
  are gated by the same flags and are likewise not reachable.
- `paxdemo`, `goddebug_intro`, `goddebug_mystery`, `ouren_test`, `level_editor`, `update125` are read in many places (demo and debug
  variants of title, cards, mystery logic); how to set them from the UI was not found. **[open]**

## 6. Using it for translation work

1. Title screen: Ctrl+Shift+H, then `U`: walk the language files line by line, F3 for the line-break mode, F2 to compare with another language.
2. Ctrl+Shift+H, then F2: flip language 0/1 live while a screen is open; F5 for Japanese combat text.
3. In a run: numpad 2 + `NNN` to open any event card (`re/debug_ids.tsv` lists them, and `woh_event.jn` has the text), numpad 5 + `NNN` for any enemy,
   numpad 0 for items, numpad 1 for status cards, numpad 4 for perks, numpad 9 for spells. This is the fastest way to see a given piece of text in context.
4. Unlock everything for testing: `save_cheat.py` (see `NOTES.md`), or the three unlock buttons plus "Give good ending".

## 7. How this was found (for re-checking after a game update)

- Debug flag, key handlers: `gml_Object_omenu_front_KeyPress_72/73/78/85`, `gml_Object_overload_KeyPress_53/113/114/115/116`, `gml_Object_o_newgod_Mouse_5`,
  `gml_Object_o_newgod_Keyboard_66`, `gml_Object_o_newgod_Step_0` -> `gml_Script_newgod_debug` (numpad console), `gml_Object_o_newgod_Draw_0` (debug tab),
  `gml_Object_omenu_front_Draw_0` (line tester). Addresses change per build; find them by name with `FuncStrings.java`.
- Tools added for this: `scripts/datawin_names.py` (asset names/ids from `data.win`, resolves the numeric ids the code passes around),
  `scripts/asmflow.py` (condense an annotated `DumpAsm` listing), `scripts/gml_summary.py` (one-screen summary of a decompiled function),
  `scripts/CodeSites.java`, `re/debug_ids.tsv` (typed-ID tables). The huge draw events and `newgod_debug` do not decompile within 30 minutes: use
  `DumpAsm.java` + `annotasm.py` + `asmflow.py` for those.
