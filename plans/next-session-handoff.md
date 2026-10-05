# Next Session Handoff

Start here. State as of 2026-10-04 (plug-in knobs, button moves, HUD work): 391
hardware-free tests pass. Everything under "Built" and "Plug-in knobs and button changes"
is **verified on the user's hardware**.

## Read first

| Doc | Why |
|---|---|
| [`TODO.md`](../TODO.md) | The backlog, organized by mode (Tracking / Step Sequencer / Mixing) |
| [`docs/quick-reference.md`](../docs/quick-reference.md) | What every APC40 button and editor menu does. Must stay in sync with the code |
| [`docs/GENERAL.md`](../docs/GENERAL.md) | Architecture, config keys, behavior notes (see *Step sequencer*), Cakewalk quirks |
| [`docs/setup-loopmidi-and-cakewalk.md`](../docs/setup-loopmidi-and-cakewalk.md) | Setup (step 6 = sequencer cables and clock, step 7 = C4 surface), troubleshooting |
| [`plans/c4-surface-plan.md`](c4-surface-plan.md) | C4 research with Cakewalk source citations; its status block lists where the build differs |
| [`plans/hud-concept.md`](hud-concept.md) | HUD design notes (HUD is built, including the C4 parameter names) |
| `logs/apc40-sonar.log` | Every HUD toast is logged as `action: ...`, plus C4 setup / LED lines: read it first when the user reports odd behavior |

## Built (and verified on hardware)

- Mixer: 8 faders, master fader, strip buttons, Pan / Send A-B-C (sends 1-3), banking,
  Tracks/Buses toggle (Master), Track Selection (from the APC40's knob dump).
- Modes on the Scene buttons: 1 = **Tracking** (startup), 2 = **Step Sequencer**,
  3 = **Mixing** (utility row 58-61 = plug-in control on the C4, see below).
- Tracking utility row: next plug-in (58), insert marker, marker jumps, selection
  start/end, loop and punch from selection, loop on/off, auto-punch (F2), metronome (F1).
  Undo / Redo are on Stop All Clips (Shift = Redo) in every mode.
- Playhead: Cue Level jog, Shift + Cue fine, Nudge with hold-repeat, Stop x2 = go to start.
- Crossfader timeline zoom; Shift hold / one-shot / lock; grid level meters; HUD; exit
  animation.
- **Step sequencer (Scene 2)**, the app's own (not Sonar's; see below):
  - Modules: `sequencer` (pattern + clock-driven player), `midi_file` (export / import),
    `clipboard` (read Sonar's copied clips), `seq_link` (UDP to the editor), `seq_editor`
    (tkinter window, own process, open only while in Scene 2). Wiring in `__main__`
    (`_open_sequencer`, `_SeqEditor`), grid mode in `engine` (`_seq_*`, `seq_command`,
    `seq_state`).
  - Ports: `APC40-SEQ` (notes to a Cakewalk drum track) and `APC40-CLOCK` (Cakewalk's MIDI
    clock in, handled in the rtmidi **callback** so notes go out on the clock, not the
    20 ms loop).
  - APC40: tap cycles off / green / amber / red; hold `LONG_PRESS_MS` (1 s) on a lit pad = off; hold + any
    Device knob = velocity; Bank arrows page steps / lanes; Clip Stop row = playhead,
    drawn 40 ms ahead of the clock (`SEQ_DISPLAY_LEAD_MS`, View > Playhead lead; the user
    found 40 right).
  - Editor: menu bar (File / Pattern / Drum map / View) + one toolbar row (Steps, Paste
    from Sonar, Export .mid); lane move / add / remove on right-click. Drum maps: GM 10 /
    16 and Addictive Drums 2 16 / 32 built in, plus saved JSON maps in
    `patterns/drum-maps/`. Export writes **format 1** `.mid` and opens Explorer on it;
    Import / Paste snap to sixteenths from the first note's bar and shrink repeating clips.
    Pattern autosaves to `patterns/current.json` (gitignored `patterns/`).
  - No-clock warning: Cakewalk playing 1.5 s with no clock -> amber message in the editor.

## Sequencer facts learned this session (do not re-learn them)

- **Sonar's own Step Sequencer cannot be driven.** The control-surface SDK exposes only
  view / insert-delete row / prev-next step / step record (`Framework2/CommandIDs.h`),
  no cell access or readback. The user chose the app's own sequencer + editor instead.
- **Cakewalk's clock output is per project** (Preferences > Project > MIDI, *Transmit MIDI
  Start/Continue/Stop/Clock*, sync port = only `APC40-CLOCK`, stored by port *number*).
  A new project sends nothing and the pattern silently does not play (hence the warning).
- **Changing MIDI Devices while Cakewalk runs disconnects the Mackie surface** until
  Cakewalk restarts (undoing the change does not help). Enable all ports, then restart.
  Clock sent to a Mackie cable floods it and loopMIDI mutes it; once this needed a full
  reboot.
- **Format-0 `.mid` files become one Sonar track per MIDI channel** (a channel-10 pattern
  made ten tracks). Always export format 1.
- **Clipboard:** Sonar's copy holds `CF_CAKEWALK_SONAR` (private), a registered
  `Standard MIDI File` format (960 PPQ, times relative to the start of the copied range)
  and `CF_RIFF` (RMID). Reading works. **Pasting into Sonar from another program is
  impossible:** Sonar pastes from its internal copy and ignores the Windows clipboard
  (tested with its private format removed; a web search found no trick). Real Sonar
  copies are test fixtures: `tests/sonar_clipboard*.mid`.
- Addictive Drums 2 is not GM (42 = snare side stick, hi-hat 48-59); source: XLN's
  keymap PDF, June 2021.

## Plug-in knobs and button changes (2026-10-04, verified on hardware)

- **C4 plug-in control:** `c4` module, handshake + LED-gated setup, Device knobs drive the
  selected track's (or bus's) plug-in in every mode, Mixing utility row: Clip/Track = next
  plug-in (Shift = previous), < / > = parameters by 8 (Shift by 1), Device On/Off = the
  plug-in's *Enable* / *Bypass* switch (skipped by the knobs). Track Selection / Master
  reset to the first plug-in. Plan and Cakewalk citations: `c4-surface-plan.md`.
- **Button moves:** Undo / Redo on **Stop All Clips** (Shift = Redo) in every mode,
  Clip/Track in Tracking = next plug-in (the user kept hitting Undo by accident). Clip
  Stop: short press clears its clip light, long press (`LONG_PRESS_MS`, 1 s, also the
  sequencer's hold-to-clear) resets the knob. Stop only stops.
- **HUD:** plug-in line + parameter row, fixed text widths (never resizes), Expanded grows
  to the left, dragged position saved (`.hud-position.json`, `HUD_MARGIN`,
  `--reset-hud-position`, off-screen fallback), every toast is also logged (`action: ...`).

Facts learned (do not re-learn them):

- **Cakewalk drops note 0** on its surfaces (MCU Rec 1, the C4's Split). The C4 therefore
  stays unsplit; all 32 V-pots are bound and the app pages its own 8-knob window.
- **Plug-in order:** the track's ProChannel modules come first, then the FX rack.
  *Exclude filters from plug-ins* **on** (recommended, in the preset) removes the two extra
  entries Cakewalk otherwise prepends (*ProChannel EQ* again, *Track Compressor*).
- **Cakewalk keeps Tracks/Buses across an app restart** but does not resend the main
  surface's LEDs; the C4 banner (refreshed on every start) tells the app which it is.
- **Clip Stop LEDs are green only** on the original APC40 (red / amber show as green).

## What to work on next

Suggested order; confirm with the user before starting a big one.

1. **Step sequencer follow-ups** (the next workflow gap, `TODO.md` *Step Sequencer*):
   - Several named patterns (save as / load / switch), maybe on the free Scenes 4-5.
   - Per-lane mute (for example Shift + a grid pad, or the editor).
   - Note names in the editor: it shows 36 = C2; XLN calls it C1, Sonar's default C3.
     **Ask the user which numbering they want** (asked once, never answered).
   - Hardware check still open: timing of recorded notes against Cakewalk's clock.
2. **Reconnect handling** (robustness, `TODO.md` *Step 9*): today a loopMIDI cable muted
   by flood protection, a Cakewalk restart that drops the surface, or an APC40 USB
   unplug needs an app restart. Detect it (no input, send errors) and reopen ports;
   re-run the C4 handshake (`Engine.c4_connect`) after reopening.
3. **Open C4 questions** (small, need the user's hardware):
   - Q2: does Cakewalk recreate the C4 surface on a project switch? The app re-runs setup
     on any serial query, so it should recover; confirm and note it.
   - Knob feel: is `C4_KNOB_STEP_LIMIT=3` right for fine EQ moves?
   - Clip light: blink the Clip Stop LED for a clip (the row is green only, the same as
     the sequencer playhead)? The user was offered it, no answer yet.
4. **Readable `--monitor`**: decode notes/CCs into names ("Undo", "C4 Slot Up") next to
   the raw bytes; useful for every future hardware debug.
5. **Ideas** (ask first; see the user's button preferences: no remapping of working
   buttons unasked, like with like):
   - The grid in Mixing mode only shows meters; it could show the track's plug-in slots
     (one pad per plug-in, lit = on, press = select / bypass).
   - Remember the parameter page per plug-in (Cakewalk's offset is global; the app could
     keep `(track, slot) -> window`).
   - Device knobs in Tracking might get another job later; `engine.DEVICE_KNOB_TARGET`
     is the switch for that.
   - Tap Tempo (99) still only flashes: needs the keystroke bridge (`TODO.md`).
   - Free Shift combos: Shift + Device On/Off (Tracking), Shift + Rec Quantize,
     Shift + MIDI Overdub, Shift + strip buttons.

## Critical Cakewalk / APC40 facts (learned the hard way)

The authority is Cakewalk's Mackie Control source: the **Cakewalk Control Surface SDK**,
<https://github.com/Cakewalk/Cakewalk-Control-Surface-SDK> (`Surfaces/MackieControl`).
Clone it into the session scratchpad when needed (`git clone --depth 1
--filter=blob:none ...`). Cite `file:line` for protocol claims.

- **Cakewalk drops real Note Off (0x80)** for its buttons. Anything it acts on at
  *release* (M1-M4 modifiers, Loop 89, cursor keys, Rewind/FF) must be released with
  **Note On velocity 0** (`mcu.cakewalk_release`), or it sticks / never toggles / repeats.
- **Cakewalk-mode button numbers** differ from the standard MCU labels: 89 = Loop,
  90 = Home, 70-73 = M1-M4, 76 = Track, 80 = Aux, 82/83 = Undo/Redo, 84-87 = Marker /
  Loop / Select / Punch navigation. There is no metronome button (use an F-key).
- **Re-pressing the active assignment button** (Pan/Send) flips the knobs to single-track
  layout, which Cakewalk never reports. Only press assignment buttons when switching.
- **All Mackie units share one static state** in Cakewalk (modifiers, selected strip);
  the C4 keeps its own assignment but shares modifiers.
- **Per-project Mackie Control preset** is required (meters, master fader = Bus, F1/F2,
  *Select highlights track*, protocol, *Disable handshake* checked). See the setup guide.
- **APC40 Generic Mode:** Track Selection sends no note (it dumps the bank's 8 Device knob
  positions); **Master sends no note either**, only its channel-8 knob dump (confirmed by
  capture); utility row and Device knobs arrive on the selected bank's channel 0-8;
  Record Arm/Solo/Activator and utility 58-61 **latch** (act on both edges); 62-65, Scene
  buttons and grid pads are momentary and the APC40 may blank LEDs on release (re-assert).
- **loopMIDI flood protection** mutes a cable (`[muted]`) on message bursts; only a
  loopMIDI restart clears it. Keep per-frame message budgets (`JOG_BUDGET_PER_FRAME`).

## Working conventions

- The user tests on hardware, then says "commit". Commit on `main` only when asked, and
  push only when asked ("commit to origin" = push `main` to `origin`, the Forgejo remote;
  a second remote `github` exists, push there only if named). Attribution line per the
  session's commit instructions.
- Every behavior change updates `docs/quick-reference.md` (plain language, no MCU jargon),
  `docs/GENERAL.md`, `TODO.md` (incl. the test count), `.env.example` for new keys, and
  this handoff. Record what the user reports from hardware as **tested**, with their
  exact observations; never mark it "not tested".
- Other Claude sessions may be editing the same checkout: check `git status` before
  editing, never stage or commit another session's files.
- **Confirm what the user means before building a big feature.** This session first built
  the wrong sequencer (the user meant Sonar's own); a two-line question would have saved
  it. Say what is and is not verified on hardware.
- Prefer Cakewalk preset settings over one-use APC40 "setup" buttons; keep layouts "like
  with like"; keep the editor uncluttered (options in menus, not toolbars).
- Visual checks of the editor: `seq_editor` can be driven by a fake app (a script that
  publishes `Engine.seq_state()` over `seq_link` to a spare port) and screenshotted with
  PowerShell `CopyFromScreen`; the screen is 3072 x 1728 at high DPI.
- Visual checks of the HUD: build `hud.HudApp` with a fake receiver whose `poll()` returns
  `{"state": hud_state.to_dict(snapshot), "info": {}}`, call `hud._set_dpi_aware()` first,
  use `opacity=1.0` and a corner away from the user's running HUD, pump `root.update()`
  and grab with Pillow (`uv run --with pillow`).
- Long doc edits: the Bash tool's heredoc breaks on some quoting; write a Python script
  file to the scratchpad and run it with `uv run python`.
