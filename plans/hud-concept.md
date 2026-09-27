# HUD concept - a tiny on-screen display for apc40sonar

Status: Phases 0-2 implemented 2026-09-27 (plus expanded strips, meters and R/S/M from
Phase 4); Phase 3 (C4) waits on `plans/c4-surface-plan.md`. Hardware checks in section 6
are still open. Author: research pass, 2026-09-27.

The APC40 has no display, so today the only feedback is LEDs. The HUD is a small,
always-on-top overlay that shows what the controller is doing and what Cakewalk
says back: knob mode, bank, selected track, the 8 knob targets, transport, time.

Source shorthand used below:

- `engine.py:NNN` etc. = `src/apc40sonar/...` in this repo.
- `CW:File.cpp:NNN` = Cakewalk's Mackie Control surface source (SDK copy in this
  session's scratchpad: `.../scratchpad/sdk/Surfaces/MackieControl/`). This is the
  authority for what Cakewalk writes to the LCD and 7-segment displays.

---

## 1. What it can show

### 1.1 Data sources that exist today vs. need adding

| Item | Source | State today |
|---|---|---|
| Knob mode (Pan / Send A-C = sends 1-3) | `Engine.knob_mode` (`engine.py:198`), set in `set_knob_mode` (`engine.py:544`) | Stored |
| Shift held | `Engine.shift` (`engine.py:202`, `:398-401`) | Stored |
| Cakewalk assignment / Edit mode | `_cw_assign`, `_cw_edit` from MCU LEDs (`engine.py:208-209`, `:647-653`) | Stored (private) |
| Loop on/off | `_loop_led` from MCU note 89 (`engine.py:211`, `:656-658`) | Stored (private) |
| Zoom mode | `_zoom_mode` from Zoom LED (`engine.py:225`, `:654-655`) | Stored (private) |
| Cakewalk meters on | `cakewalk_meters_on()` (`engine.py:711`) | Derived from meter traffic |
| Per-track meter level / clip latch | `_meter_level`, `_meter_clip` (`engine.py:216-218`, `:687-709`) | Stored |
| Transport Play / Stop / Record | MCU notes 93-95 (`engine.py:641-646`) | **Rendered to LEDs, not stored** - add fields |
| Rec / Solo / Mute / Select per strip | MCU notes 0-31 (`engine.py:633-640`) | **Rendered, not stored** - add fields |
| Metronome-during-record (Shift+Metronome = F1) | `engine.py:137-139` | **No state from Cakewalk** - show as a toast only |
| Track bank offset | `Engine.bank` is a placeholder (`engine.py:200`); TODO notes Cakewalk does not report the strip offset (`TODO.md:126-127`) | Unknown - derive (see 3.4) |
| Timecode / BBT | MCU CC 64-73; ignored because `on_mcu_cc` only accepts ring CCs (`engine.py:661`) | **Add decoder** |
| Assignment 2-char display | MCU CC 74-75 (`docs/mcu-mapping.md:140-141`) | **Add decoder** |
| LCD text (track names, param labels/values, temp messages) | SysEx `F0 00 00 66 <dev> 12 <offset> <chars> F7` (`docs/mcu-mapping.md:81`); dropped twice: `midi_io.open_input(ignore_sysex=True)` (`midi_io.py:114-132`) and `mcu.decode` returns `None` for status >= 0xF0 (`mcu.py:276`) | **Add capture + decoder** |

### 1.2 What Cakewalk actually writes (from its source)

- **LCD geometry:** 2 x 56 chars, `LCD_SIZE` 111 (`CW:MackieControlLCDDisplay.h:11-12`).
  Offset = `line*56 + x` (`CW:MackieControlLCDDisplay.cpp` `Write`). Cakewalk sends
  **only the changed span** of a line (leading/trailing unchanged chars skipped), so the
  receiver must keep a 112-char buffer and patch it.
- **Upper line** = 8 x 7-char cells, track name (6 chars, crunched) per strip
  (`CW:MackieControlXTTxDisplay.cpp:87-131`, `:216-262`). With M1+Name/Value it shows
  `Trk  9` style numbers instead (`:239-242`, `CW:MackieControlMasterRx.cpp:473-474`).
- **Lower line** = 8 x 7-char cells, the V-pot's param **label** by default, or its
  **value** after plain Name/Value (`CW:MackieControlXTTxDisplay.cpp:135-175`, `:266-298`;
  default `m_bDisplayValues=false`, `CW:MackieControlState.cpp:81`).
- **Value peek:** turning a V-pot makes that strip's upper cell show the value for
  `TEMP_DISPLAY_TIMEOUT` = 20 refreshes (`CW:MackieControlXTRx.cpp:124`,
  `CW:MackieControlBase.h:35`, `CW:MackieControlXTTxDisplay.cpp:224-238`). At Cakewalk's
  50-75 ms refresh that is roughly 1-1.5 s.
- **Temp message (whole upper line, centered):** on strip Select it writes
  `Track 5: "Vocals"` (`CW:MackieControlXT.cpp:349-410`, called from
  `CW:MackieControlXTRx.cpp:338`); in plug-in modes it adds `Plugin n: "Name"`;
  master-fader reassignment writes `Master Fader = Bus 1` (`CW:MackieControlMaster.cpp:1300-1360`).
- **Meters + text:** in LEDs+Meters mode the lower-line text under each existing strip
  is replaced by LCD bar meters (`CW:MackieControlXTTxDisplay.cpp:144-174`). Our
  Shift+Detail View toggle normally lands on "Signal LEDs" (`engine.py:717-759`), which
  keeps the text.
- **Other screens:** `No Cakewalk Project Loaded`, `Display Updates Disabled`, layout mode
  (`CW:MackieControlXTTxDisplay.cpp:33-63`, `:89-94`).
- **Timecode:** cell *n* (left to right) is CC `0x40 | (9-n)`, i.e. CC 73 is leftmost,
  CC 64 rightmost, on channel 0 (`CW:MackieControlMaster.cpp:67`,
  `CW:MackieControl7SegmentDisplay.cpp:73-83`). Value bit 6 = dot, bits 0-5 = char
  (0x40-0x5F folded down by 0x40, `:42-56`). BBT layout `"%3d%02d  %03d"` =
  measure(3) beat(2) blank(2) tick(3) (`CW:MackieControlMasterTx.cpp:315`); SMPTE
  `"%3s.%02d.%02d.%3s"` (`:302`). Only sent when the time changes (`:239-240`).
- **Assignment display:** CC 75 = left char, CC 74 = right char
  (`CW:MackieControlMaster.cpp:64`). Values `PN`, `SE`, `PL`, `EQ`, `FG`, `DY`, `TR`...;
  **a dot on the second char means channel-strip layout** (`CW:MackieControlMasterTx.cpp:145-222`)
  - a free detector for the "layout flip" the engine works hard to avoid (`engine.py:572-586`).
- **Device byte:** Cakewalk fills byte 4 from the handshake or its expected type, 0x14 for
  the main surface, 0x17 for C4 (`CW:MackieControlMaster.cpp:50`, `CW:MackieControlC4.cpp:54`,
  `CW:MackieControlBase.cpp:221-242`). Accept any `0x10-0x17` rather than hard-coding.

### 1.3 Prioritized content

| Priority | Item | Needs SysEx? |
|---|---|---|
| **Must** | Knob mode: `PAN` / `SEND A (1)` / `SEND B (2)` / `SEND C (3)` | No |
| **Must** | Transport: stopped / playing / recording | No (store LED state) |
| **Must** | Loop on/off, Zoom mode active, Cakewalk meters on/off, Shift held | No |
| **Must** | Toasts on actions: "Send B", "Bank >", "Channel <", "Zoom fit", "Meters off", "Metronome (rec) toggled", "Go to start", "Stop all" | No |
| **Must** | Link status: MCU ports open / Cakewalk feedback seen in last N s | No |
| Nice | Selected strip (from Select LEDs) and track name/number (from the temp message) | Yes |
| Nice | 8 strip cells: track name + current knob value (label/value from LCD, peek values) | Yes |
| Nice | Bank "Tracks 9-16" (derived, 3.4) | Yes |
| Nice | BBT / SMPTE time | No SysEx (CC 64-73) |
| Nice | Assignment chars + channel-strip warning | No (CC 74-75) |
| Nice | Cakewalk temp messages mirrored as toasts (`Track 5: "Vocals"`) | Yes |
| Later | Plug-in parameter names/values for the Device knobs via the C4 surface (4 LCD rows, SysEx cmd `0x30-0x33`, `CW:MackieControlC4.cpp:61`) | Yes (C4 port) |
| Later | Mini level meters per strip (data already in engine) | No |
| Later | Per-strip R/S/M badges | No |
| Later | Grid mode / step-sequencer page once those exist (`TODO.md` step 8) | No |

---

## 2. Technology options (Windows, Python 3.14)

Checked 2026-09-27: the project interpreter is CPython 3.14.7 and `import tkinter`
works with **Tk 9.0** (`uv run python -c "import tkinter"`). PyPI: PySide6 6.11.2
ships `cp310-abi3-win_amd64` wheels (stable ABI, so it should install on 3.14; not
tested here); Dear PyGui 2.3.1 has wheels only up to cp313 (**no 3.14**); pywebview
6.2.1 is pure Python and pulls `pythonnet` on Windows, which has cp314 wheels (3.1.0).

| Option | 3.14 availability | Dep weight | Topmost / alpha / click-through | Threading with the 20 ms loop | Looks | Verdict |
|---|---|---|---|---|---|---|
| **tkinter (stdlib)** | Yes, Tk 9.0 present | None | `-topmost`, `-alpha`, `overrideredirect`, `-transparentcolor` built in; click-through via `ctypes` `SetWindowLongW(WS_EX_LAYERED \| WS_EX_TRANSPARENT)` | Tk wants its own thread/main loop; in-process `root.update()` would stall during a window drag (Windows modal move loop) | Plain but fine for a dark text panel; Tk 9 has better scaling | **Recommended (separate process)** |
| PySide6 / Qt | abi3 wheel, likely OK (verify) | ~150-250 MB installed | Best: `WindowStaysOnTopHint`, `WA_TranslucentBackground`, `WindowTransparentForInput` | Qt owns main thread; needs worker thread or separate process | Best | Fallback if looks matter |
| pywebview (Edge WebView2) | Yes (pure + pythonnet cp314) | pythonnet + .NET runtime + WebView2 | `on_top=True`, frameless, transparent partly; click-through not built in | Blocks main thread (`webview.start()`) | HTML/CSS, very flexible | Heavy for a strip; maybe later |
| Dear PyGui | **No cp314 wheel** | ~20 MB | Viewport always-on-top yes; click-through no | Own render loop | Good for meters | Rejected (3.14) |
| Local web page (stdlib `http.server` + SSE/WebSocket, opened as `msedge --app=`) | Yes, stdlib (SSE) | None | Edge app window is not always-on-top or click-through | Server thread in-process, or separate process | HTML/CSS | Good for a second-screen/tablet view, not as an overlay |
| Console-title / tray only | Yes | None | n/a | Trivial | Minimal | Too little info |

**Process model:**

| Model | Isolation | Complexity | Notes |
|---|---|---|---|
| In-process, same thread (`root.update()` in the loop) | None: a drag, resize, or Tk exception stalls MIDI | Lowest | Rejected |
| In-process, HUD thread | Partial: GIL shared, a crash can kill the app | Low | Tk must be created and used only in its thread; workable but fragile |
| **Separate process, UDP JSON on 127.0.0.1** | Full: HUD crash/hang never touches MIDI; engine send is a non-blocking `sendto` | Low-medium | Also lets a browser view or other client subscribe later |

**Recommendation:** tkinter HUD in a **separate child process** (`python -m apc40sonar.hud`),
fed by fire-and-forget UDP JSON snapshots. Zero new dependencies, Tk 9.0 is already in
the interpreter, and the MIDI loop only ever does a non-blocking `sendto`.
**Fallback:** the same child process rewritten in PySide6 (same UDP protocol) if the Tk
look or click-through proves unsatisfying; the web page is a later "second screen" option.

---

## 3. Architecture

```text
 APC40 --> engine (20 ms loop) --> MCU out
 MCU in ---^   |  (incl. SysEx LCD, CC 64-75)
               v
          HudState (pure, in engine)  --snapshot on change, <= 20 Hz-->  HudPublisher
                                                                          | UDP 127.0.0.1:HUD_PORT
                                                                          v
                                                          apc40sonar.hud child process (tkinter)
```

### 3.1 Engine side (hardware-free, unit-testable)

- New module `hud_state.py`: a frozen dataclass `HudSnapshot` (knob mode, shift, transport,
  loop, zoom, meters on, selected strip, strip names[8], strip values[8], lcd lines[2],
  time string, assignment chars, strip-layout flag, bank offset or None, meter levels[8],
  toasts list, seq no.) plus pure functions to build it from engine state.
- `Engine` gets a `self.version` counter bumped on any HUD-relevant change and a small
  `self._toasts: deque[(text, frame)]`; `engine.toast("Send B")` is called beside existing
  actions (`set_knob_mode`, Bank arrows `engine.py:420-426`, `_on_stop_press`,
  `toggle_cakewalk_meters`, crossfader fit `engine.py:471-478`, Shift+Metronome).
- `Engine.hud_snapshot()` returns the immutable snapshot. No sockets, no Tk in the engine;
  tests assert snapshot contents after feeding messages, exactly like `tests/test_engine.py`.
- Store what is now only rendered: transport LEDs and per-strip R/S/M/Select in
  `on_mcu_note` (`engine.py:627-658`).

### 3.2 MCU display capture

- `midi_io.open_input(..., ignore_sysex=False)` for the MCU input only (the APC40 input keeps
  ignoring it). Pass a flag from `_open_mcu` (`__main__.py:116-140`) when `HUD=on`.
- `mcu.decode` (`mcu.py:263-303`): return `DecodedMessage("sysex", ...)` for `F0 ... F7`
  instead of `None`.
- New `mcu_display.py` (pure):
  - `LcdBuffer`: 112-char buffer; `apply(sysex)` checks `F0 00 00 66 <0x10-0x17> 12 off chars F7`,
    patches `buf[off:off+len]`, maps non-ASCII bytes to spaces; `line(n)`, `cell(line, strip)`
    (7-char cells); detects centered temp messages (upper line not cell-aligned) and returns
    them as toast candidates.
  - `SevenSeg`: 12 cells; `apply(cc, value)` for CC 64-75 on channel 0 or 15
    (`docs/mackie_control_protocol.md:420-446`); `timecode()` renders `ttt.bb.ttt`-style,
    `assignment()` returns 2 chars + dot flag.
- `Engine.on_mcu_message` routes `sysex` to `LcdBuffer` and CC 64-75 to `SevenSeg`
  (before the ring-only return at `engine.py:661`).
- Cost: Cakewalk sends only changed spans, so steady state is light; during playback the
  timecode CCs change every refresh (~15-20 msgs/s), trivially cheap.

### 3.3 Publishing, throttling, lifecycle

- `hud_link.py` (the only I/O part): `HudPublisher(port)` with a non-blocking UDP socket.
  In the run loop (`__main__.py:248-254`), after `eng.tick()`: if `eng.version` changed and
  >= 50 ms since last send (20 Hz cap), send `json.dumps(snapshot)`; always send a heartbeat
  once per second. Full snapshots (~1-2 KB) make packet loss harmless.
- Everything wrapped in `try/except OSError`: a missing listener never raises
  (`sendto` on UDP to a closed port may raise `ConnectionResetError` on Windows - swallow it).
- Launch: when `HUD=on`, `subprocess.Popen([sys.executable, "-m", "apc40sonar.hud", ...])`
  with `CREATE_NO_WINDOW`; terminate it in the existing `finally` (`__main__.py:259-260`).
  If it exits, log once and relaunch with backoff (max ~3 tries), never block.
- The HUD process: tkinter window, `after(30 ms)` poll of a non-blocking UDP socket,
  keeps only the newest snapshot, greys out and shows "no link" after 3 s without heartbeat.
  It can also be run by hand (`uv run python -m apc40sonar.hud`) to attach to a running app.
- Optional `--hud` / `--no-hud` CLI flags override the config.

### 3.4 Bank offset (Cakewalk does not report it)

Cheapest reliable derivation: on a strip Select, Cakewalk lights Select LED *i*
(notes 24-31) and writes `Track N: "name"` (`CW:MackieControlXT.cpp:349-410`), so
**offset = N - 1 - i**. Keep it until a Bank/Channel press (then mark "?" until the next
select, or adjust by +/-8/+/-1 provisionally). Alternative: M1+Name/Value track-number
mode shows `Trk  9` in every cell, but it changes Cakewalk's display state, so do not
toggle it silently.

### 3.5 Config keys (`.env`, parsed like `config.py:138-179`)

| Key | Default | Meaning |
|---|---|---|
| `HUD` | `off` (MVP), `on` later | Launch the HUD child process |
| `HUD_PORT` | `47040` | UDP port on 127.0.0.1 |
| `HUD_POSITION` | `top-right` | `top-left` / `top-right` / `bottom-*` or `x,y` |
| `HUD_MONITOR` | `0` | Monitor index for placement |
| `HUD_OPACITY` | `0.85` | Window alpha 0.2-1.0 |
| `HUD_TOPMOST` | `on` | Always on top |
| `HUD_CLICK_THROUGH` | `off` | Mouse passes through (then move it via config only) |
| `HUD_LAYOUT` | `compact` | `compact` / `expanded` |
| `HUD_TOAST_MS` | `1200` | Toast duration |
| `HUD_LCD` | `on` | Capture MCU SysEx/7-seg (turns off `ignore_sysex` on the MCU input) |

### 3.6 Failure isolation rules

1. The engine never imports tkinter or socket code; only `hud_link` does I/O.
2. Publishing is non-blocking, rate-capped, exception-swallowing, and skipped entirely when `HUD=off`.
3. The HUD is another process: its crash, hang, or window drag cannot stall MIDI.
4. SysEx decode errors are logged once per kind and dropped (handler isolation already exists in `_drain`, `__main__.py:143-166`).

---

## 4. UX sketch

Dark theme (near-black `#16181c`, text `#e6e6e6`, accent per mode: Pan = amber,
Send A/B/C = cyan/violet/green, each distinct), monospace
for the strip cells, default placement top-right over Cakewalk's toolbar area, draggable
with the mouse when click-through is off, right-click menu: compact/expanded, opacity, quit.

**Compact strip (~420 x 80 px):**

```text
+--------------------------------------------------------------+
| SEND B (2)   Trk 9-16   Sel: 12 Vocals        > PLAY  LOOP   |
|  37:02:000                         Z  M  SHIFT     [ Bank > ] |
+--------------------------------------------------------------+
```

Left: mode (big, colored). Middle: bank + selected track. Right: transport + state
badges (Z = zoom mode, M = Cakewalk meters on). Bottom-right: the latest toast, fading.

**Expanded (~560 x 170 px):**

```text
+--------------------------------------------------------------------------+
| SEND B -> send 2        Tracks 9-16     Sel 12 "Vocals"    [] STOP  LOOP |
| BBT  37.02.000          Assign SE       Meters on   Zoom   Shift         |
|--------------------------------------------------------------------------|
|  Kick    Snare   OH      Bass    Gtr L   Gtr R   Vocals  Pad             |
|  -12.0   -inf    -6.5    -9.1    -8.0    -8.0    -3.2    -18.0           |
|  ||||    |       ||||||  |||||   ||||    |||     ||||||| ||              |
|--------------------------------------------------------------------------|
|  Track 12: "Vocals"                                    (toast, 1.2 s)    |
+--------------------------------------------------------------------------+
```

Row 2 = LCD upper line (names), row 3 = lower line (values when Name/Value is in value
mode, else labels; the V-pot value peek briefly replaces a name, shown highlighted).
Selected strip is outlined. Channel-strip layout (assignment dot) shows a red "Strip
layout!" badge. A later C4 panel adds a row of 8 plug-in parameter names/values for the
Device knobs.

---

## 5. Phased plan

| Phase | Scope | Tests |
|---|---|---|
| **0. Plumbing** | `HudSnapshot` + `Engine.hud_snapshot()`, version counter, toast queue; store transport and R/S/M/Select LED state; `hud_link` UDP publisher; config keys; `HUD=off` default | Snapshot after `set_knob_mode`, meter toggle, loop LED, transport notes; toast emitted per action; publisher rate cap with a fake clock and fake socket; config parsing |
| **1. MVP HUD** | tkinter child process: mode, transport, loop/zoom/meters/shift badges, link status, toasts; topmost + opacity + position; spawn/terminate/respawn | HUD view-model (snapshot -> strings) is a pure function and unit-tested; Tk window itself verified manually |
| **2. MCU displays** | SysEx capture on the MCU input, `LcdBuffer`, `SevenSeg`, strip cells, BBT/SMPTE, assignment + strip-layout warning, temp-message toasts, selected track name, derived bank offset | Feed recorded Cakewalk byte streams (capture with `--monitor` once SysEx is on) into `LcdBuffer`; partial-span patching; timecode CC ordering (CC 73 leftmost); dot handling; bank derivation from Select + temp text |
| **3. C4 names** | Once `plans/c4-surface-plan.md` lands: decode C4 LCD (`F0 00 00 66 17 30..33 ...`) on the C4 input, show Device-knob param names/values | Same buffer tests with 4 rows |
| **4. Extras** | Mini meters, R/S/M badges, click-through, expanded layout polish, optional web view on the same UDP feed | View-model tests |

MVP definition: Phases 0-1 - mode + send number, transport, loop/zoom/meters/shift,
toasts, link status. No SysEx, no new dependencies.

## 6. Risks and open questions

1. **Tk topmost vs. Cakewalk:** `-topmost` can lose to other topmost windows or fullscreen
   plug-in UIs; Tk 9 + `overrideredirect` + per-monitor DPI needs a hands-on check.
   Click-through via `WS_EX_TRANSPARENT` is ctypes-only and makes the window undraggable.
2. **SysEx over loopMIDI/rtmidi:** confirm Cakewalk actually sends the LCD SysEx to our
   port (it does for a registered MCU, but the device byte depends on the handshake; the
   app never answers it) and that rtmidi's WinMM SysEx buffers deliver whole messages
   (messages are <= 120 bytes, so default buffers should do). Verify with `--monitor`.
3. **Bank / selection truth:** the bank offset is inferred (3.4), not reported; it is
   unknown until the first Select after a bank move. Also, temp messages and value peeks
   overwrite cells for ~1-1.5 s, so the HUD must tell "name" from "peek" (compare with the
   last stable name per cell).
4. **Lower-line content depends on Cakewalk state** (labels vs. values via Name/Value, text
   hidden in LEDs+Meters mode). Open question: should the app press Name/Value once at
   startup to get values on the lower line? It changes Cakewalk's own state.
5. **Metronome (F1) and Send param position** have no Cakewalk feedback; the HUD can only
   echo what the app sent, and must label it as such.
6. **Packaging:** a child process needs the same interpreter (`sys.executable`); fine under
   `uv run` and `run-apc40-sonar.cmd`, re-check if the app is ever frozen (PyInstaller).
7. **PySide6 fallback** is untested on 3.14 (abi3 wheel should install); Dear PyGui is out
   until it ships cp314 wheels.
