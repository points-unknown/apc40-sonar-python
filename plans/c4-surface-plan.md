# Plan: second surface "Mackie Control C4" for the Device Control knobs

Status: research done, nothing implemented. Builds on the TODO item "Second surface: Mackie
Control C4 for the Device Control knobs".

## Summary

- Cakewalk's **Mackie Control C4** is a separate surface class inside the same
  `MackieControl.dll` as the main Mackie Control. It has **4 rows x 8 V-pots**, 4 two-line
  LCDs and its own mode buttons. With the right setup, **row 1 = 8 parameters of the
  selected track's current plug-in**, with per-parameter ring feedback and LCD names and
  values. That is what the APC40 Device Control knobs need.
- **The C4 has no "Disable handshake" option.** Cakewalk drops every C4 input until the app
  answers its serial-number query with SysEx. This is a hard requirement (see P1).
- The C4 **follows the main surface's selected strip** (shared `m_cState`) unless its Lock
  is on. So the existing Track Selection -> MCU Select path already retargets the C4.
  Plug-in slot, parameter page and assignment are **local to the C4**. Paging and plug-in
  stepping cannot disturb the main surface's Pan/Send layout.
- The C4's split mode and assignment are **not persisted** by Cakewalk. The app must
  re-apply "Split 1/3 + Upper assignment = Plugin" after every handshake. Split 1/3 is
  needed: in the default "no split" mode the upper section spans all 32 V-pots and paging
  clamps at `numParams - 32`, so plug-ins with fewer than 32 parameters cannot be paged.
- Recommended mapping: Device knobs -> C4 row 1. Left/Right arrows (60/61) = parameter page
  -/+8, Shift = -/+1. Clip/Track (58) = next plug-in, Shift+58 = previous plug-in.
  Device On/Off (59) = bypass only if a Cakewalk command can be bound to a C4 function key
  (open question); otherwise it stays free for now.

Source root for all citations:
`scratchpad/sdk/Surfaces/MackieControl/` (sparse clone of Cakewalk-Control-Surface-SDK).
Short names: `C4.cpp` = `MackieControlC4.cpp`, `C4.h`, `C4Rx`, `C4Tx`, `C4TxDisplay`,
`C4State`, `C4Reconfigure` = `MackieControlC4*.cpp`. `Base.cpp`/`Base.h` =
`MackieControlBase.*`, `Binder` = `MackieControlBaseBinder.cpp`, `State` =
`MackieControlState.*`, `LCD` = `MackieControlLCDDisplay.*`, `VPotDisp` =
`MackieControlVPotDisplay.cpp`.

---

## 1. Protocol reference

### 1.1 Identity and handshake (P1)

| Item | Value | Source |
|---|---|---|
| Friendly name in Cakewalk | `Mackie Control C4` | C4.h:38 |
| Expected device type | `0x17` | C4.cpp:54 |
| Serial query (Cakewalk -> app) | `F0 00 00 66 17 1A 00 F7` | Base.cpp:491-502 |
| When the query is sent | On each surface refresh while no serial is known, and only once a project is loaded | Base.cpp:289-292, 497-498 |
| Reply the app must send (app -> Cakewalk) | `F0 00 00 66 17 1B s0 s1 s2 s3 s4 s5 s6 F7` (7 serial bytes, any values) | Base.cpp:209-214, 238-257; `LEN_SERIAL_NUMBER 7` MackieControlInformation.h:7 |
| Effect of the reply | Sets `m_bDeviceType` = reply byte 4 (use `0x17`, because LCD SysEx reuses it), marks the surface connected and forces a full refresh (all LEDs, rings, LCD) | Base.cpp:242-251; LCD.cpp:251 |
| Before the reply | **All short messages are ignored** | Base.cpp:138-139 |
| Disable-handshake bypass | Only on the Master (main) surface; the C4 uses the base query | Master.cpp:1119-1148 vs Base.cpp:491 |
| Wake-up (app -> Cakewalk) | `F0 00 00 66 17 01 ... F7` resets the handshake: Cakewalk forgets the serial, re-queries, and after the reply force-refreshes everything | Base.cpp:216-225 |
| Status text | "Connecting..." until handshake, then e.g. `Trk 3` | C4.cpp:147-168, 489-510 |
| Unit identity | Unique ID from Cakewalk, **not** the serial; the serial value does not matter | Base SurfaceGen.cpp:56; State.cpp:990-1005 |
| Strip offset | The C4 does **not** take an 8-strip offset slot (only XT/Master do), so adding it does not shift the main surface's banks | State.cpp:955-959; Base.h:49-55 |

What the app sends when it connects: (1) a **Wake-up** to force a known state even if
Cakewalk kept an old C4 instance, then (2) answer **every** `1A` query with the `1B` reply.
The reply can also be sent unprompted: it is accepted whenever no serial is held
(Base.cpp:238-240). It only works once Cakewalk has opened the port (`m_bConnected`,
Base.cpp:187).

### 1.2 C4 input (app -> Cakewalk)

Cakewalk only dispatches status `0x90` (buttons) and `0xB0` (V-pots) (C4.cpp:438-452).
A button counts as "down" **only at velocity 0x7F exactly**; any other value is "up"
(C4Rx:71). Presses must be `90 nn 7F` and releases `90 nn 00`. Real Note Off (0x80) is
dropped, as on the main surface.

| ID | Button | Behavior in Cakewalk | Source |
|---|---|---|---|
| 0x00 | Split | Cycles None -> 1/3 -> 2/2 -> 3/1 -> None (M1 reverses) | C4.h:94-95; C4Rx:121-154 |
| 0x03 | Lock | Toggles lock of the focused split; **copies main's strip type, assignment and selection** | C4Rx:158-174 |
| 0x04 | Spot Erase | Swaps focus between upper and lower split (split modes only) | C4Rx:178-187 |
| 0x05 | Marker | Held: Bank/Param/Track buttons move the Now time / markers instead | C4Rx:191-202, 288-292 |
| 0x06 | Track | Held: V-pot pushes select strip type / assignment (see 3.2) | C4Rx:206-231, 543-591 |
| 0x07 | Chan Strip | Toggles channel strip <-> multi-channel for the focused split | C4Rx:235-247 |
| 0x08 | Function | Toggles Function mode (32 V-pot pushes = commands, F1-F8 user-bindable) | C4Rx:251-257, 594-639 |
| 0x09 / 0x0A | Bank Left / Right | Parameter offset -8 / +8 (M1: first / last) | C4Rx:286-338 |
| 0x0B / 0x0C | Param Left / Right | Parameter offset -1 / +1 (M1: first / last) | C4Rx:342-394 |
| 0x0D-0x10 | Shift / Option / Control / Alt | M1-M4 modifiers, **linked to the main surface**; in plug-in modes they also shift the parameter offset (buggy formula) | C4Rx:96-99, 261-282; C4.cpp:76 |
| 0x11 / 0x12 | Slot Up / Down | Plug-in index +1 / -1 (M1: last / first) | C4Rx:398-450 |
| 0x13 / 0x14 | Track Left / Right | Moves the selected track ±1 (M2: ±8); **changes the shared selection** when unlocked | C4Rx:454-520; C4State:246-290 |
| 0x20-0x3F | V-pot push, row r (0-3), col c (0-7): `0x20 + 8r + c` | Normal: toggle a bool or reset to default (M1: arm automation) | C4.h:101-108; C4Rx:73-83, 524-541 |

V-pot rotation: `B0 cc vv`, with `cc = 8*row + col` (`0x00-0x1F`, row 1 = `0x00-0x07`)
(C4Rx:23-29). `vv`: bit 6 (0x40) = counter-clockwise; low nibble = speed 1-15
(C4Rx:30, 38). Step = `stepSize * ((v-1)*3 + 1)`, so v=1 -> 1x, 2 -> 4x, 3 -> 7x
(C4Rx:38-43). **v must never be 0**: it gives a -2x step, which is a reversed direction.
Unmapped plug-in parameters use `DT_LEVEL` with a 0.005 step (0.5 % per tick)
(Binder:714-715). M1 held on either surface = x0.1 fine (C4Rx:45-49).
V-pot turns are ignored outside Normal mode, for example while Track or Function is active
(C4Rx:26).

### 1.3 C4 output (Cakewalk -> app)

**Rings.** `B0 cc vv` with `cc = 0x20 + 8*row + col`; row 1 = `0x20-0x27`
(C4.cpp:66-70; VPotDisp.cpp:142-147). This is the MCU ring byte: bits 0-3 = position,
bits 4-5 = mode, bit 6 = center LED (VPotDisp.cpp:76-135).

| Data type | Mode bits | Position | Source |
|---|---|---|---|
| `DT_NO_LEDS` (unbound / empty) | 0 | 0 -> byte `0x00` | VPotDisp.cpp:59-62, 87-89 |
| `DT_LEVEL` (default for plug-in params) | `0x20` wrap | `round(v*11)`, 0-11 | VPotDisp.cpp:91-92, 121-123 |
| `DT_PAN`/`BOOL`/`SELECTOR`/`BOOST_CUT` | 0 (`0x10` boost/cut) | `1 + round(v*10)` | VPotDisp.cpp:95-100, 117-119 |
| `DT_SPREAD` / `REVSPREAD` | `0x30` | `1 + round(v*5)` | VPotDisp.cpp:103-127 |

In Normal mode, byte `0x00` therefore means "no parameter here". A `DT_LEVEL` at 0 is
`0x20`. In Track/Function mode the rings become on/off indicators (`0x46` = on)
(C4Tx:35-91, 136-183). The engine must not render those.

**LEDs.** `90 id vv`: `0x00` off, `0x01` blink, `0x7F` on (Base.cpp:537-552).

| LED id | On when | Source |
|---|---|---|
| 0x00 / 0x01 / 0x02 | Split 1/3 / 2/2 / 3/1 (all off = no split) | C4Tx:189-191 |
| 0x03 | Lock on the focused split | C4Tx:193 |
| 0x04 | Lower split focused | C4Tx:192 |
| 0x05 | Marker mode | C4Tx:194 |
| 0x06 / 0x08 | Track mode / Function mode | C4Tx:195, 197 |
| 0x07 | Channel strip mode on the focused split | C4Tx:196 |

**LCD SysEx.** `F0 00 00 66 17 <lcd> <offset> <ascii...> F7`
(LCD.cpp:26-31, 231-257):

- `<lcd>` = `0x30 + row` (0x30-0x33), one per V-pot row (C4.cpp:60-61).
- 2 lines x **56** chars (`LCD_WIDTH 56`); `offset = line*56 + x`. `LCD_SIZE` is **111**,
  so offset 111 (the last character) is never sent (LCD.h:10-12; LCD.cpp:183-191).
- **Writes are partial diffs.** Unchanged leading and trailing characters are skipped
  unless it is a forced refresh (LCD.cpp:193-222). The parser must patch a 112-byte buffer
  at the given offset.
- Other SysEx on the same port: meter mode `F0 00 00 66 17 20 id val F7` and global meter
  mode `.. 21 ..` (LCD.cpp:261-289); meter levels `D0|row` (LCD.cpp:121-130). Ignore all of
  these.

What Cakewalk writes on LCD row 1 (`0x30`) in our target mode (Normal, channel strip,
upper split = row 0):

| Line | Content | Source |
|---|---|---|
| Line 0 (offsets 0-55) | 8 cells of 7: parameter label crushed to 6 chars + space | C4TxDisplay:113-141, 256-294 (channel strip -> `GetCrunchedParamLabel`, :268-270) |
| Line 1 (56-110) | 8 cells of 7: **value** text, 6 chars + space | C4TxDisplay:147-173, 298-323 (channel strip forces values, :303-304) |
| Temporary banner on line 0 | 56-char centered text for 20 refreshes, e.g. `Track 3: "Vox", Plugin 2: "Sonitus Delay"` or `... Plugin 3: --None--` | C4.cpp:547-621; C4TxDisplay:117-120; `TEMP_DISPLAY_TIMEOUT 20` Base.h:35 |
| When the banner fires | Every Slot Up/Down (**even when the slot did not change**); Track Left/Right; assignment change | C4State:118-150 (banner at :148 is outside the change check); C4Rx:483-484; C4Reconfigure:123-127 |
| Main "Display Name/Value" flip | Swaps the two lines (shared flag) | C4TxDisplay:126-135, 149-167; MasterRx:426 |
| Main "Disable LCD updates" | Line 0 = "Display Updates Disabled", values blank | C4TxDisplay:105-111, 306-322 |
| No project | Row 0: "No Cakewalk Project Loaded" | C4TxDisplay:24-35 |

---

## 2. How the C4 picks its target (research Q4)

| State | Scope | Default | Source |
|---|---|---|---|
| Mixer strip type (Track/Bus/Master) | Main's (`m_cState`) unless locked | Track | C4State:23-47 |
| Selected strip | **Main's `m_cState.GetSelectedStripNum()`** unless locked | follows main | C4State:246-290 |
| Assignment (Params/Sends/Pan/Plugin/EQ/Dyn) | **Local per split** (the "linked" comment is stale) | `PARAMETER` | C4State:55-74; C4.cpp:103 |
| Assignment mode | Local per split | **Channel strip** | C4State:102-105; C4.cpp:104 |
| Plug-in slot | Local `[split][strip type][assignment]`: **not per track** | 0 | C4State:113-150; C4.h:260 |
| Parameter offset | Local `[split][strip type][assignment][mode]`: **not per track or plug-in** | 0 | C4State:158-195; C4.h:261 |
| Lock | Upper unlocked, **lower locked** | | C4.cpp:89-115 |
| Split | None (upper = all 32 V-pots) | | C4.cpp:77; C4.cpp:639-649 |
| Modifiers | Linked to main (`m_bLinkModifiers = true`) | | C4.cpp:76; C4State:344-378 |

- **Binding in channel strip mode:** each V-pot `n` of the section gets parameter
  `paramOffset + n` of plug-in `pluginOffset` on the selected strip (C4Reconfigure:263-279
  -> `ConfPlugin` -> `ConfigurePlugins(..., PT_ALL, ...)`, Binder:601-606, 673-778).
  Plug-ins without an ini mapping bind `MIX_PARAM_FX_PARAM` directly (Binder:704-717).
- **Plug-in list order:** if the main page's "Exclude filters from plug-ins" is **off**,
  the ProChannel EQ and the Track Compressor filters are prepended as slots 0/1
  (Binder:842-910; option on the main page, MackieControl.rc:139, saved by Master.cpp:465).
  Slot clamping is 0..`MAX_PLUGINS` (99), **not** the track's plug-in count
  (C4State:122-127; Base.h:47). Stepping past the last plug-in unbinds everything and the
  banner shows `--None--` (C4.cpp:589-595; Binder:912-918).
- **Paging clamp in channel strip mode:** `offset + (vpotsInSection - 1) < numParams`
  (C4State:171-187). With **no split** (32 V-pots) any plug-in with fewer than 32 params
  is stuck at offset 0, and bigger ones page to `numParams-32`. With **Split 1/3** the upper
  section is 8 V-pots on row 1 (C4.cpp:645; C4Reconfigure:33-35), so pages are
  0, 8, 16, ... with the last page clamped to `numParams-8`. **Use Split 1/3.**
- **Getting "row 1 = 8 params of the selected track's current plug-in":**
  1. Split: press `0x00` until LED `0x00` is on (from None: one press) (C4Rx:139-147).
  2. Upper assignment = Plugin: press Track `0x06` (hold), press V-pot push **row 2 col 4**
     = `0x2B` (`0x20 + 8*1 + 3`), then release Track. In Track mode, row index 1 targets
     the **upper** split and col 3 = Plugin (C4Rx:543-590, esp. :545, :585). Releasing
     Track returns to Normal (C4Rx:218-229). This step is idempotent
     (`SetAssignment` no-ops if unchanged, C4State:67-73).
  3. Channel strip mode is already the default (LED `0x07` on); do not touch it.
- **Selection follows the main surface:** the app's MCU Select calls
  `m_cState.SetSelectedStripNum`, which bumps `m_dwC4UpdateCount` (State.cpp:235-254).
  The C4 then rebinds on its next refresh (C4Reconfigure:172-178). With "Select highlights
  track" on, clicking a track in Cakewalk also moves the shared selection
  (XTReconfigure.cpp:29-30), so the C4 follows mouse selection as well.

---

## 3. Interactions with the main surface (research Q5)

`static CMackieControlState m_cState` is shared by every Mackie unit (Base.h:257;
Base.cpp:27).

| Coupling | Direction | Risk | Mitigation |
|---|---|---|---|
| Modifiers M1-M4 (linked) | Main -> C4 | While the engine holds main M1 (send-param selection) or M4 (zoom-fit), a C4 reconfigure would use the M1/M4 ini maps. For unmapped plug-ins M4 **unbinds** every V-pot (Binder:701-774, 790-796; C4Reconfigure:243). M1 = fine resolution (C4Rx:45-49). | These holds are sub-frame bursts. Accept, but never hold main modifiers across frames. |
| Modifiers | C4 -> Main | C4 Shift/Option/Control/Alt set the **main's** modifiers and shift the C4 param offset with a buggy formula (C4Rx:261-282) | **Never send C4 0x0D-0x10.** |
| Selected strip | both ways | C4 Track L/R (0x13/0x14) and Cakewalk's `SetStripRange` on the C4 move the shared selection (C4State:274-290; C4.cpp:235-249) | Never send 0x13/0x14; track selection stays on the main surface Select. |
| Strip type | Main -> C4 | Main Track/Bus/Master buttons retarget the C4 (C4State:23-29) | The engine does not send them today; note it in the docs. |
| Lock | C4 snapshot of main | Lock copies the main's assignment into the C4 (C4Rx:166-170) | Never send 0x03. |
| Spot Erase / Marker / Function | C4 local | Would redirect paging to the lower split or the Now time | Never send 0x04/0x05; Function only inside the bypass macro (5.3). |
| Display flip / Disable LCD updates / Exclude filters | Main settings -> C4 LCD and plug-in order | Line swap, blank LCD, slot numbering | Document: keep flip off, LCD updates on, and pick Exclude filters deliberately. The HUD parser can detect a swap (values vs labels). |
| Param/plug-in offsets, assignment | C4 local | **None**: C4 paging never touches the main's `m_dwParamNumOffset` (C4State:158-195 vs State.cpp:193-205) | Main Pan/Send A/B/C layouts are safe. |
| C4 state bumps | C4 -> Main | `BumpToolbarUpdateCount` only (toolbar redraw) | None |

**Rule:** the C4 driver only ever emits notes `0x00, 0x06, 0x08, 0x09, 0x0A, 0x0B, 0x0C,
0x11, 0x12, 0x20-0x27, 0x2B`. Unit tests enforce this whitelist.

Separate ports are mandatory. Each surface grabs its whole input port
(`GetNoEchoMask` = 0xFFFF, Base.cpp:315-329), and C4 note/CC numbers overlap MCU ones
(e.g. `0x00` = MCU Rec 1 vs C4 Split).

---

## 4. Proposed APC40 mapping

| APC40 control | Channel | C4 action | Notes |
|---|---|---|---|
| Device knobs 1-8 (CC 16-23, absolute) | bank 0-8 | V-pot row 1 col 1-8: `B0 (0x00+i) vv` | Absolute -> relative per knob; v = min(\|delta\|, limit), sign in 0x40, never 0 |
| Device rings (CC 16-23 position, 24-31 style) | **current bank channel** | From C4 ring CC `0x20+i` | `0x00` -> style Off; wrap -> Volume; pan/boost -> Pan; spread -> Volume. Reuse `mcu.decode_ring` / `RING_STYLE_FROM_MCU` |
| Left arrow 60 / Right arrow 61 | bank | Bank Left `0x09` / Bank Right `0x0A` (params -/+8) | Flash LED as acknowledgement |
| Shift + 60 / 61 | bank | Param Left `0x0B` / Right `0x0C` (-/+1) | Uses the engine's local Shift, not C4 Shift |
| Clip/Track 58 | bank | Slot Up `0x11` (next plug-in) | If the banner shows `--None--`, step back to slot 0 (wrap) |
| Shift + 58 | bank | Slot Down `0x12` (previous plug-in) | Clamps at 0 |
| Device On/Off 59 | bank | **Phase 2:** bypass via a C4 function-key macro (5.3) if feasible; until then unassigned | Open question Q1 |
| Track Selection (bank switch dump) | new bank | Existing MCU Select on the main surface; the C4 follows | Plus the reset in 4.1 |
| Master bank (channel 8) | 8 | No select (as today); the C4 stays on the last track | Open question Q5 |

Track Control knobs (CC 48-55) and all main-surface behavior stay unchanged. Today
`Engine.mixer` is always `True`, so the Device knobs only feed the knob-dump detector
(engine.py:287-295, 199). The C4 adds function without taking any away.

### 4.1 Interplay with the 9 APC banks

- **Current bank.** The engine tracks `device_bank` = the channel of the last Device CC
  (16-23) or utility-row note (58-65) with channel < 9, and the dump-settled channel.
  It starts at 0.
- **Ring writes go to `device_bank`.** `Apc40Output.ring_position/ring_style` currently
  always use channel 0 (apc40.py:285-290, 323-331); add a `channel=` argument. Keep a
  cache of the 8 C4 ring bytes, and on bank change re-render them **forced** on the new
  channel. Writing the rings re-references the APC knobs; that is intended.
- **Knob baselines per bank.** `_device_knob_abs` is keyed by knob only
  (engine.py:214, 294). A bank switch dumps the new bank's 8 positions, and small
  differences (≤ `KNOB_NOISE_THRESHOLD`) would become **spurious C4 turns**. Fix: the first
  value on a new channel only sets the baseline (key `(bank, knob)` or clear the store on
  a channel change). Dump CCs never emit V-pot moves.
- **Reset on track change (configurable, default on).** After a settled dump emits the
  MCU Select:
  1. Send Slot Down `0x12` × `slot_mirror` to go to slot 0. It clamps at 0 (C4State:124),
     and at least one press is sent so the banner shows the new track and plug-in names
     (C4State:148).
  2. Send Bank Left `0x09` × `ceil(page_mirror/8)` to go to page 0. It clamps at 0
     (C4State:186-187).
  Reason: slot and page offsets are not per track (C4.h:260-261), so a stale slot 3 on a
  track with 1 plug-in leaves dead knobs. The engine mirrors are upper bounds, and extra
  presses are harmless because both clamp at 0.

### 4.2 Knob feel

The existing `knob_step_limit` (3) and noise gate carry over. On the C4, v = 1/2/3 gives
1/4/7 ticks = 0.5 % / 2 % / 3.5 % of range for unmapped plug-ins (C4Rx:38-43;
Binder:715). Add an optional `C4_KNOB_STEP_LIMIT` so this can be tuned separately from the
main V-pots. Ini-mapped plug-ins use their own step sizes (Binder:821-822).

---

## 5. Architecture

### 5.1 New module `src/apc40sonar/c4.py` (pure, no I/O, like `mcu.py`)

- Constants: `DEVICE_TYPE = 0x17`, the button IDs from 1.2, `CC_VPOT_ROW1 = 0x00`,
  `CC_RING_ROW1 = 0x20`, `LCD_ID_BASE = 0x30`, `LCD_WIDTH = 56`, `LCD_SIZE = 111`,
  `SWITCH_WHITELIST`.
- Encoders: `vpot_delta(row, col, delta)` (value never 0), `button_press(id)` ->
  `(0x90,id,0x7F)`, `button_release(id)` -> `(0x90,id,0x00)`,
  `serial_reply(serial7)`, `wake_up()`, `setup_plugin_assignment()` -> the Track-hold
  macro list.
- Decoders: `is_serial_query(msg)`, `parse_lcd(msg) -> (row, offset, bytes) | None`
  (ignores `0x20`/`0x21`), ring decode (reuse `mcu.decode_ring`).
- `C4Display`: four 112-byte buffers patched by `parse_lcd`. It provides `labels(row)` /
  `values(row)` (7-char cells, stripped), `banner(row)` (regex
  `^(Track|Bus|Master|Aux|VMain) .*Plugin (\d+): (.*)$` on line 0 -> track, slot, plug-in
  name, or `None` for `--None--`), and a `version` counter / `on_change` callback. This is
  the **HUD feed**: a future overlay reads `engine.c4.display` and does not parse MIDI
  itself. Because line 0 alternates between banner and labels, keep `last_labels`
  (captured when line 0 matches the 8x7 cell layout) and `last_banner` separately.
- `C4State` (engine-side mirror): `connected`, `split_led`, `chanstrip_led`,
  `function_led`, `track_led`, `slot_mirror`, `page_mirror`, `rings[8]`, and
  `setup_pending`.

### 5.2 Ports, config, main loop

- `.env` keys (config.py `DEFAULTS` + `Config`): `C4_OUT_PORT` (app -> Cakewalk, default
  `APC40-C4-IN`), `C4_IN_PORT` (Cakewalk -> app, default `APC40-C4-OUT`), optional
  `C4=on|off` (default on if the ports open), `C4_KNOB_STEP_LIMIT`, `C4_RESET_ON_SELECT`.
  Also list them in `--list`/config report (`__main__._report_config`).
- `__main__._open_c4()`: best-effort like `_open_mcu` (\_\_main\_\_.py:116-140). The input
  must be opened with **`ignore_sysex=False`** (midi_io.py:114-131 ignores SysEx by
  default). If either port is missing, log a warning and the Device knobs keep today's
  behavior.
- Loop: `_drain(c4_in, eng.on_c4_message, "c4", ...)` next to the MCU drain
  (\_\_main\_\_.py:249-253). `Engine(..., c4_send=...)` gets an optional callable.
- Startup: after `render_baseline`, `eng.c4_connect()` sends `wake_up()` and one
  unprompted `serial_reply()`.

### 5.3 Engine routing (`engine.py`)

- `on_c4_message(msg)`:
  - Serial query -> send `serial_reply()`, set `setup_pending = True`.
  - Forced refresh (the first LED/LCD traffic after the reply) -> mark `connected`.
  - Note -> update the LED mirror.
  - CC `0x20-0x27` -> cache and render on the Device rings of `device_bank`, suppressed
    while the Track/Function LED is on.
  - LCD SysEx -> `C4Display`, and `log.debug` the decoded banner/labels.
- `tick()`: runs the setup state machine when `setup_pending` and LED state is known.
  (a) If LED `0x04` (lower focus) is on -> abort with a warning, since a manual Spot Erase
  would need fixing. (b) Press Split `(target - current) mod 4` times from the LED mirror
  (None = 0, 1/3 = 1, 2/2 = 2, 3/1 = 3). (c) Run the Plugin-assignment macro.
  (d) Slot Down once (banner). Then clear `setup_pending`. Split is **not idempotent**, so
  it is gated on LEDs. The assignment macro is idempotent and can be re-sent any time.
- `on_apc_cc` Device branch: track `device_bank`, set baselines on bank change, and when
  C4 is connected send `c4.vpot_delta(0, i, delta)`. The dump detector is unchanged.
- `on_apc_note` utility row (currently folds the bank channel away, engine.py:378-383):
  handle 58/60/61 (+Shift) before the global map when C4 is connected. The existing
  Shift+62 (meters) and 65 (Loop/F1) keep precedence.
- Bypass macro (phase 2, only if Q1 resolves): Function `0x08` press+release -> V-pot
  push `0x20+k` (F(k+1)) press+release -> Function `0x08` again (C4Rx:251-257, 594-607).
  Suppress ring rendering until the Function LED is off again.

### 5.4 Docs to update when implemented

`docs/setup-loopmidi-and-cakewalk.md` (second port pair and surface),
`docs/GENERAL.md` (C4 section and HUD feed), `docs/quick-reference.md` (58/59/60/61 and
Shift combos, Device knobs), `docs/cakewalk-command-matrix.md` (replace the "V-pot
multiplexing" note: the Device knobs now use their own surface), `TODO.md` sub-tasks.

---

## 6. Cakewalk setup steps

1. loopMIDI: add two cables `APC40-C4-IN` and `APC40-C4-OUT` (named after Cakewalk's
   point of view, like the existing pair).
2. Cakewalk > Preferences > MIDI > Devices: enable both new ports as input and output.
3. Preferences > Control Surfaces > **Add** > `Mackie Control C4`. Input =
   `APC40-C4-IN`, Output = `APC40-C4-OUT`. Keep the existing `Mackie Control` entry
   unchanged (protocol Cakewalk/SONAR Mode, Disable handshake checked, Select highlights
   track checked).
4. C4 property page: only F1-F8 command bindings and display names
   (MackieControl.rc:156-195; saved per C4 instance, C4.cpp:260-353). No handshake option
   exists. Split, assignment and lock are not saved; the app re-applies them.
5. Main Mackie Control page: decide **Exclude filters from plug-ins**
   (MackieControl.rc:139). Recommended **checked**, so slot 1 = first FX-bin plug-in.
   Leave "Disable LCD updates" off.
6. Load a project. The C4 status turns from "Connecting..." to e.g. `Trk 1` once the app
   answers the query (queries only start with a project loaded, Base.cpp:497).
7. No separate Cakewalk preset is needed. The C4 function-key bindings persist with the C4
   surface entry. For the bypass macro, bind F1 to the chosen command.

---

## 7. Test plan

### 7.1 Hardware-free unit tests (`tests/test_c4.py`, `tests/test_engine.py`)

- `c4.vpot_delta`: CC = `8*row+col`; +1 -> `0x01`, -1 -> `0x41`, clamp 15; delta 0 ->
  `None`; value never `0x00` or `0x40`.
- Button encoders: press = `0x90 id 0x7F`, release = `0x90 id 0x00`; never status `0x80`.
- `serial_reply`: exact bytes `F0 00 00 66 17 1B` + 7 + `F7`; `is_serial_query` for
  `F0 00 00 66 17 1A 00 F7` only.
- `parse_lcd`: full write, partial diff at an offset, offset + len clamped at 111, meter
  SysEx ignored, wrong device type ignored.
- `C4Display`: labels/values from 7-char cells; banner regex (track, slot, name,
  `--None--`); swapped lines tolerated.
- Engine:
  - A Device CC on channel 3 sends C4 CC `0x0i` to `c4_send` (not `mcu_send`).
  - A bank switch dump sends no V-pot messages and resets baselines.
  - C4 ring `0x2B`/`0x20` values render on channel = current bank; after a bank change
    all 8 are re-rendered forced on the new channel; `0x00` -> style Off.
  - Rings are suppressed while the Track or Function LED is on.
  - 60/61 -> `0x09`/`0x0A`; Shift+60/61 -> `0x0B`/`0x0C`; 58 -> `0x11`; Shift+58 -> `0x12`.
  - Setup state machine: split presses computed from the LED mirror (0/1/2/3 cases), the
    assignment macro order `06↓ 2B↓ 2B↑ 06↑`, and no split press before LED state is known.
  - Reset-on-select sends ≥1 Slot Down and `ceil(page/8)` Bank Lefts.
  - **Whitelist:** fuzz all APC inputs; every C4 note ∈ `SWITCH_WHITELIST`.
  - No C4 port: Device knobs behave exactly as today, and existing tests pass unchanged.
- Config: new keys parsed with defaults; `_open_c4` opens the input with
  `ignore_sysex=False` (mock `midi_io`).

### 7.2 Hardware checklist

1. Start the app with the C4 surface added: the Cakewalk C4 status goes from
   "Connecting..." to `Trk n`. The log shows the query/reply and the setup sequence.
2. The C4 Split LED mirror = 1/3. Restart the app while Cakewalk runs: Wake-up ->
   re-handshake -> no double split.
3. Select track 1 with an EQ plug-in: Device knobs move params 1-8 and the Cakewalk plug-in
   UI follows. Rings match the values. Parameters that do not exist show rings off.
4. 61/60 page by 8 (a 20-param plug-in pages 0 -> 8 -> 12); Shift = by 1.
5. 58 steps to the next plug-in (banner logged with its name); past the last it wraps to
   the first; Shift+58 goes back.
6. Track Selection 1 -> 2 -> 1: the C4 retargets, slot and page reset, rings show on the
   new bank. No parameter moves during the bank switch (compare before/after values).
7. Pan / Send A/B/C on the Track Control knobs are unaffected before, during and after
   C4 paging (main layout does not flip).
8. The crossfader zoom-fit (M4 hold) and Send A select (M1 hold) do not leave the C4
   unbound (turn a Device knob right after).
9. Master bank (channel 8): Device knobs keep controlling the last track's plug-in.
10. Reload a project and switch projects: the C4 re-handshakes and setup re-applies.
11. Unplug or rename the C4 loopMIDI ports: the app starts with a warning and the Device
    knobs behave as today.

---

## 8. Risks and open questions (ranked)

1. **Handshake and instance lifecycle (high).** Without the `1B` reply the C4 ignores
   everything (Base.cpp:138). Split and assignment are lost whenever Cakewalk recreates the
   surface. It is unverified whether that happens on project switch or only on restart or
   re-adding the surface. Mitigation: answer every query, treat each query as "re-run
   setup", gate the non-idempotent Split on LED feedback, and Wake-up at app start.
2. **Shared-state bleed (high).** Linked modifiers mean main M1/M4 holds can momentarily
   rebind the C4 (M4 = unbound for unmapped plug-ins). Main Display-flip, LCD-disable and
   Exclude-filters settings change C4 output. Several C4 buttons (Lock, Track L/R,
   modifiers) would mutate main state. Mitigation: the strict note whitelist, short
   modifier holds, and documented settings. Verify item 8 on hardware.
3. **APC bank / ring channel handling (medium-high).** Rings written on the wrong channel
   are invisible, and a stale per-knob baseline turns bank dumps into parameter jumps.
   Ring writes re-reference knobs, and the existing noise gate must still absorb that.
   Needs careful tests and hardware item 6.
4. **Offsets are global, not per track (medium).** The plug-in slot and param page carry
   across tracks and clamp only on shift (C4State:113-195). Reset-on-select fixes the
   common case but discards the user's page when switching back.
5. **Bypass not available on the C4 (medium, Q1).** The C4 has no bypass control. The only
   route is binding a Cakewalk command to an F-key (C4 property page enumerates Cakewalk's
   command list, C4PropPage.cpp:488-519). It is unknown whether a per-plug-in or FX-bin
   bypass command exists there. Fallback: leave 59 unassigned, or use the planned keystroke
   route in `docs/cakewalk-command-matrix.md`.
6. **LCD parsing ambiguity (low-medium).** Line 0 alternates between banner and labels, and
   writes are diffs. Plug-in and track names appear only in the banner, which is triggered
   deliberately via Slot Down. Needs `ignore_sysex=False`; loopMIDI SysEx throughput under
   heavy refresh is unmeasured.
7. **Knob resolution (low).** 0.5 % per tick at v=1 may feel slow; v=0 reverses. Tune with
   `C4_KNOB_STEP_LIMIT` on hardware.
8. **Extra setup burden (low).** Two more loopMIDI cables and a second surface entry. The
   feature stays optional and off without the ports.

Open questions to settle on hardware:

- Q1: Which Cakewalk commands appear in the C4 F-key list, and is there a focused-FX or
  FX-bin bypass?
- Q2: Does Cakewalk recreate the C4 (losing split/assignment) on project switch?
- Q3: Does the first forced refresh after the reply always include all 9 LEDs? (`m_bLEDs`
  starts at `0xFF` so it should, Base.cpp:73-77.)
- Q4: Is the default for "Exclude filters from plug-ins" on or off in current Cakewalk?
- Q5: Should the Master bank (channel 8) lock the C4 to the master bus plug-ins (needs the
  C4 strip type = Master, which is shared with the main unless locked)?
