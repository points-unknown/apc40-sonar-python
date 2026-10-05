# Next Session Handoff

Start here. State as of commit `0e5438d` (2026-09-27): 314 hardware-free tests pass,
working tree clean. Everything under "Built" is **verified on the user's hardware**.

## Read first

| Doc | Why |
|---|---|
| [`TODO.md`](../TODO.md) | The backlog, organized by mode (Tracking / Step Sequencer / Mixing) |
| [`docs/quick-reference.md`](../docs/quick-reference.md) | What every APC40 button and editor menu does. Must stay in sync with the code |
| [`docs/GENERAL.md`](../docs/GENERAL.md) | Architecture, config keys, behavior notes (see *Step sequencer*), Cakewalk quirks |
| [`docs/setup-loopmidi-and-cakewalk.md`](../docs/setup-loopmidi-and-cakewalk.md) | Setup (section 6 = sequencer cables and clock), troubleshooting |
| [`plans/c4-surface-plan.md`](c4-surface-plan.md) | The next big feature (Mixing mode) |
| [`plans/hud-concept.md`](hud-concept.md) | HUD design (HUD is built; phase 3 = C4 param names) |

## Built (and verified on hardware)

- Mixer: 8 faders, master fader, strip buttons, Pan / Send A-B-C (sends 1-3), banking,
  Tracks/Buses toggle (Master), Track Selection (from the APC40's knob dump).
- Modes on the Scene buttons: 1 = **Tracking** (startup), 2 = **Step Sequencer**,
  3 = **Mixing** (utility row 58-61 reserved for C4 plug-in control; does nothing yet).
- Tracking utility row: undo/redo, insert marker, marker jumps, selection start/end, loop
  and punch from selection, loop on/off, auto-punch (F2), metronome (F1).
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
  - APC40: tap cycles off / green / amber / red; hold 1 s on a lit pad = off; hold + any
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

## Next, in priority order

1. **Plug-in knobs (C4) are built (2026-10-04, uncommitted until the user says so).**
   Verified on hardware: handshake, Device knobs move plug-in parameters, Clip/Track steps
   plug-ins in Mixing, the HUD plug-in line. Learned on hardware: **Cakewalk drops note 0,
   so the C4's Split button cannot be pressed**; the C4 stays unsplit and the app pages its
   own 8-knob window over the 32 bound parameters (`Engine._c4_window`). ProChannel
   modules are listed as the first plug-ins (the user likes that). Plug-ins whose first
   parameter is *Enable* / *Bypass* start the knobs at parameter 2; Device On/Off (59)
   presses that switch. Still to test: < / > paging, Device On/Off, the on/off skip.
   Open: project-switch behavior (Q2), knob speed (`C4_KNOB_STEP_LIMIT`).
   HUD changes the same day: fixed text widths (no resizing), Expanded grows to the left,
   dragged position saved in `.hud-position.json` (`HUD_MARGIN`, `--reset-hud-position`,
   off-screen fallback), no banner toast.
2. **Sequencer follow-ups** (`TODO.md`): several named patterns (maybe on Scenes 4-5),
   per-lane mute, note names in the editor matching Sonar's octave numbering (the editor
   shows 36 = C2; XLN says C1; Sonar's default says C3: the user was asked, no answer yet).
3. **Reconnect handling**: recover when loopMIDI mutes/drops a cable or the APC40 USB
   disconnects, without restarting the app.
4. **Readable `--monitor`**: decode notes/CCs into names ("Undo", "Marker nav + FF").

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

- The user tests on hardware, then says "commit". Commit locally on `main` only when
  asked; do not push. Attribution line per the session's commit instructions.
- Every behavior change updates `docs/quick-reference.md` (plain language, no MCU jargon),
  `docs/GENERAL.md`, `TODO.md` (incl. the test count), and `.env.example` for new keys.
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
