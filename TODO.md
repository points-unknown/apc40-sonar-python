# TODO / Roadmap

Working backlog for apc40sonar. `README.md` is the big-picture quickstart;
`docs/GENERAL.md` is the detail; this file is what is left to build.

## Where we are

Of the 9 migration steps in [`plans/apc40-sonar-python-plan.md`](plans/apc40-sonar-python-plan.md):

- Steps 1-7 are done: scaffold, `midi_io`, `apc40`/`mcu`, `engine` mixer core, feedback
  rendering, startup lightshow, and end-to-end validation with Cakewalk.
- Remaining: **step 8** (grid modes, device/plug-in control, global commands) and
  **step 9** (polish), below.
- 73 hardware-free tests pass. Pan smoothing and latching-toggle fixes are in.

## Step 8 - complete the control surface

### Utility row (notes 58-65)

- [ ] Clip/Track (58): switch the Track Control knobs between track and clip context
- [ ] Device On/Off (59): focused plug-in bypass, with the LED reflecting state
- [ ] Left / Right arrows (60/61): Device Control knob page or parameter bank
- [ ] Detail View (62): local view toggle or keystroke
- [ ] Rec Quantize (63): keystroke (`Ctrl+Alt+R`) with local flash
- [ ] MIDI Overdub (64): keystroke (`Ctrl+Alt+O`) with the Overdub LED from feedback
- [x] Metronome (65): MCU Click (done)

### Scene buttons (notes 82-86)

- [ ] Map scenes to MCU F1-F5, or to Cakewalk screensets, or to local grid modes
- [ ] Reflect the active scene/screenset on the Scene LEDs

### Device / plug-in mode

- [ ] Mode switch between **mix mode** (Track Control knobs -> V-pots) and **device mode**
  (Device Control knobs -> V-pots)
- [ ] Assign Plug-in (43), EQ (44), Instrument (45) plus V-pot CC 16-23
- [ ] Render MCU ring feedback to the **Device** rings (CC 16-23 + style 24-31) in device mode
- [ ] Send A/B/C selection: choose which send the Track Control knobs address (Assign Send 41)
  and show the send level in the rings

### Navigation and transport

- [ ] Bank +/- (MCU 46/47) and Channel +/- (48/49) from APC buttons; show the bank on the grid
- [ ] Master fader (APC CC 14) -> MCU Pitch Bend ch 8
- [ ] Considering the crossfader (APC CC 15): map to a configurable CC or leave unused
- [ ] Rewind/Forward, Cycle, Punch/Drop, Nudge, Zoom, Scrub, Markers
- [ ] Shift as a modifier for alternate button functions
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
- [ ] Refresh the MIDIMonster-era wording in
      [`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md) to the Python app

## Ideas to make the APC40 most useful in Cakewalk/SONAR

Ordered roughly by value-to-effort:

- [ ] **Track level meters on the Clip Stop LEDs** - read MCU channel-pressure meters and
      render an 8-segment bar per track. High value, self-contained.
- [ ] **Follow the selected plug-in (auto-map)** - on track/plug-in selection, point the
      Device Control knobs at the focused plug-in's parameters and show names via a
      small on-screen overlay or log. Makes device mode genuinely useful.
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
- Known limitation: Cakewalk's Mackie Control ignores MCU Rec note 0, so APC Track 1
  Record Arm cannot arm track 1 over the surface (use the mouse). Do not reintroduce the
  Remote Control workaround - it conflicts with the Mackie Control surface.
