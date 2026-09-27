# TODO / Roadmap

Working backlog for apc40sonar. `README.md` is the big-picture quickstart;
`docs/GENERAL.md` is the detail; this file is what is left to build.

## Where we are

Of the 9 migration steps in [`plans/apc40-sonar-python-plan.md`](plans/apc40-sonar-python-plan.md):

- Steps 1-7 are done: scaffold, `midi_io`, `apc40`/`mcu`, `engine` mixer core, feedback
  rendering, startup lightshow, and end-to-end validation with Cakewalk.
- Remaining: **step 8** (grid modes, device/plug-in control, global commands) and
  **step 9** (polish), below.
- 99 hardware-free tests pass. Pan smoothing and latching-toggle fixes are in.

## Step 8 - complete the control surface

### Utility row (notes 58-65)

- [ ] Clip/Track (58): switch the Track Control knobs between track and clip context
- [ ] Device On/Off (59): focused plug-in bypass, with the LED reflecting state
- [ ] Left / Right arrows (60/61): Device Control knob page or parameter bank
- [ ] Detail View (62): local view toggle or keystroke (Shift + Detail View = Cakewalk meters on/off, done)
- [ ] Rec Quantize (63): keystroke (`Ctrl+Alt+R`) with local flash
- [ ] MIDI Overdub (64): keystroke (`Ctrl+Alt+O`) with the Overdub LED from feedback
- [x] Metronome (65): MCU Click (done)

### Scene buttons (notes 82-86)

- [ ] Map scenes to MCU F1-F5, or to Cakewalk screensets, or to local grid modes
- [ ] Reflect the active scene/screenset on the Scene LEDs

### Device / plug-in mode

- [ ] Mode switch between **mix mode** (Track Control knobs -> V-pots) and **device mode**
  (Device Control knobs -> V-pots). The switch exists in the engine (`Engine.mixer`) but
  no button toggles it yet, so the Device Control knobs currently do nothing
  - [ ] Choose the button that toggles mix/device (e.g. Clip/Track 58 or Shift + Pan)
  - [x] Handle Mode 0 Device Control banking: the knobs and the utility row (58-65)
        report on the **selected track's channel** (0-7, Master = 8); the engine accepts
        channels 0-8 and writes utility-row LEDs to all nine banks (done)
- [ ] Assign Plug-in (43), EQ (44), Instrument (45) plus V-pot CC 16-23
- [ ] Render MCU ring feedback to the **Device** rings (CC 16-23 + style 24-31) in device mode
- [ ] Send A/B/C selection: choose which send the Track Control knobs address (Assign Send 41)
  and show the send level in the rings

### Navigation and transport

- [ ] Bank +/- (MCU 46/47) and Channel +/- (48/49) from APC buttons; show the bank on the grid
- [ ] Master fader (APC CC 14) -> MCU Pitch Bend ch 8
- [ ] Considering the crossfader (APC CC 15): map to a configurable CC or leave unused
- [ ] Rewind/Forward, Cycle, Punch/Drop, Nudge, Zoom, Scrub, Markers
- [ ] Bank Select arrows (94-97) currently send MCU cursor Up/Down/Left/Right; decide
      cursor vs. bank/channel (e.g. plain = bank, Shift = cursor)
- [ ] Nudge + / - (100/101): unassigned; candidates are MCU Rewind/Forward or Nudge
- [ ] Tap Tempo (99): only flashes its LED; needs the keystroke bridge for real tap tempo
- [ ] Cue Level knob (CC 47, relative): unassigned; candidate is the MCU jog wheel (CC 60)
      for scrub/shuttle
- [ ] Master button (80): only stays lit; candidates are select the master bus or MCU Flip.
      Note it also switches the Device Control bank to channel 8 in Mode 0
- [ ] Footswitches 1 / 2 (CC 64 / 67): unassigned; candidates are Play/Stop and Record
- [ ] Cycle feedback is shown on the Rec Quantize LED as a placeholder; move it to
      whichever button ends up owning Cycle
- [ ] Shift as a modifier for alternate button functions (layer in place; Shift + Detail View mapped)
- [ ] Track Control knob buttons (the switches under the knobs)

## Keystroke bridge (part of step 8/9)

- [ ] Choose and add an input-injection dependency (`pydirectinput` or `pynput`)
- [ ] Assign the dedicated conflict-free keymap in Cakewalk (see
      [`docs/cakewalk-command-matrix.md`](docs/cakewalk-command-matrix.md))
- [ ] Implement a `keys` module: emit press/release sequences for a combo
- [ ] Wire the keyboard-only commands: tap tempo, auto punch, redo, quantize, loop from
      selection, selection start/end, split, MIDI overdub, record quantize, view toggles,
      screensets, plug-in bypass

## Step 9 - polish and robustness

- [ ] Reconnect handling: detect loopMIDI/APC40 disappearing and recover without restart
- [ ] Move the control mapping into the config file so functions can be reassigned without code
- [ ] Decoded `--monitor` (human-readable note/CC names) alongside the raw dump
- [ ] Configurable log level and log rotation size
- [ ] Shutdown behavior: decide whether to leave the ready state or clear the panel on exit
- [ ] Fallback for Windows MIDI Services loopback endpoints when loopMIDI is unavailable
- [x] Refresh the MIDIMonster-era wording in
      [`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md) to the Python app

## Ideas to make the APC40 most useful in Cakewalk/SONAR

Ordered roughly by value-to-effort:

- [x] **Track level meters** - MCU channel-pressure meters render as a 5-segment bar per
      track on the clip grid, with a latched clip indicator on Clip Stop (done; `METERS`).
- [ ] **Follow the selected plug-in (auto-map)** - on track/plug-in selection, point the
      Device Control knobs at the focused plug-in's parameters and show names via a
      small on-screen overlay or log. Makes device mode genuinely useful.
- [ ] **Second surface: Mackie Control C4 for the Device Control knobs** - add a
      Cakewalk *Mackie Control C4* surface beside the main *Mackie Control* so the
      Device Control knobs get dedicated plug-in control while the Track Control knobs stay
      on pan/sends (no mix/device mode switch; see "V-pot multiplexing" in
      [`docs/cakewalk-command-matrix.md`](docs/cakewalk-command-matrix.md)). Pairs with the
      auto-map item above. Keep the main surface as regular Mackie Control; XT and C4 are
      add-ons, not replacements.
  - [ ] Research the C4 protocol (SysEx device ID, V-pot CC/note layout for the 4 encoder
        rows, ring feedback, LCD) and what Cakewalk's C4 plug-in modes expose
  - [ ] Two more loopMIDI cables (e.g. `APC40-C4-IN` / `APC40-C4-OUT`) plus
        `C4_OUT_PORT` / `C4_IN_PORT` keys in `.env`; opened best-effort like the MCU pair
  - [ ] `c4` encoder/decoder module; route Device Control knobs (CC 16-23) to C4 row 1 and
        render C4 ring feedback on the Device rings (CC 16-23 + style 24-31)
  - [ ] Decide what Left/Right arrows (60/61) and Device On/Off (59) do in C4 context
        (parameter page, bypass)
  - [ ] Update `docs/setup-loopmidi-and-cakewalk.md` and `docs/GENERAL.md` with the
        optional second surface
- [ ] **Send-level control with rings** - Send A/B/C buttons plus the Track Control knobs
      set send levels, with the rings showing the send amount.
- [ ] **Session/bank overview on the grid** - use the 8x5 grid to show which bank of tracks
      is active and which clips/scenes exist, instead of blank pads.
- [ ] **Shift modifiers** - Shift + strip button = alternate action (e.g. Shift+Mute =
      clear all mutes; Shift+Scene = record-enable scene).
- [ ] **Screensets on Scene buttons** - one-press workspace switching; remember the last one.
- [ ] **Transport extras** - Cycle/loop toggle, punch, marker jump, zoom, scrub mapped to
      free buttons with feedback where MCU provides it.
- [ ] **Grid modes** - drum-pad mode (send notes to an instrument track) and clip-launch
      mode, matching the `docs/cakewalk-command-matrix.md` specialization.
- [ ] **Metronome and Overdub LEDs** - faithful state from MCU feedback (partly done for
      Metronome; add Overdub).
- [ ] **Template + setup doc** - a ready-made Cakewalk project template (tracks, keymap,
      surface config) so setup is one import.
- [ ] **Performance pass** - throttle/coalesce feedback, batch LED writes, and cap per-frame
      messages to keep the event loop smooth under heavy knob movement.

## Notes

- Documentation policy: big picture only in `README.md`; all detail in `docs/GENERAL.md`.
  Every feature that changes a control's behavior also updates `docs/quick-reference.md`.
- Known limitation: Cakewalk's Mackie Control ignores MCU Rec note 0, so APC Track 1
  Record Arm cannot arm track 1 over the surface (use the mouse). Do not reintroduce the
  Remote Control workaround - it conflicts with the Mackie Control surface.
