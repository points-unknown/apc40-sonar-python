# TODO / Roadmap

Working backlog for apc40sonar. `README.md` is the big-picture quickstart;
`docs/GENERAL.md` is the detail; this file is what is left to build.

## Where we are

Of the 9 migration steps in [`plans/apc40-sonar-python-plan.md`](plans/apc40-sonar-python-plan.md):

- Steps 1-7 are done: scaffold, `midi_io`, `apc40`/`mcu`, `engine` mixer core, feedback
  rendering, startup lightshow, and end-to-end validation with Cakewalk.
- Remaining: **step 8** (grid modes, device/plug-in control, global commands) and
  **step 9** (polish), below.
- 116 hardware-free tests pass. Pan smoothing and latching-toggle fixes are in.

## Step 8 - complete the control surface

### Utility row (notes 58-65)

- [ ] Clip/Track (58): switch the Track Control knobs between track and clip context
- [ ] Device On/Off (59): focused plug-in bypass, with the LED reflecting state
- [ ] Left / Right arrows (60/61): Device Control knob page or parameter bank
- [ ] Detail View (62): local view toggle or keystroke (Shift + Detail View = Cakewalk meters on/off, done)
- [ ] Rec Quantize (63): keystroke (`Ctrl+Alt+R`) with local flash
- [ ] MIDI Overdub (64): keystroke (`Ctrl+Alt+O`) with the Overdub LED from feedback
- [x] Metronome (65): Cakewalk Loop on/off (note 89; Cakewalk mode has no Click), LED = loop
      state. Shift + Metronome = metronome during record via Mackie F1, assigned to
      *Metronome During Record* in the preset (done)

### Scene buttons (notes 82-86)

- [ ] Scenes select the **grid mode**: Scene 1 = meters (or pads with `METERS=off`),
      Scene 2 = step sequencer, Scenes 3-5 reserved for future grid modes (drum pads,
      clip launch). The lit Scene LED shows the active grid mode
- [ ] Screensets / MCU F1-F5 move elsewhere (e.g. Shift + Scene) if still wanted

### Step sequencer grid mode (Scene 2)

The clip grid becomes a pattern editor that plays drum/note lanes in sync with Cakewalk.

Layout:

```text
            step 1 ... step 8        (current page of 8 steps)
grid row 1  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 1   ^
grid row 2  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 2   |  Bank Select Up/Down:
grid row 3  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 3   |  lanes 1-5, 6-10, ...
grid row 4  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 4   |
grid row 5  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 5   v
Clip Stop   [ ][ ][*][ ][ ][ ][ ][ ]  playhead (lit = step now playing)
            <-- Bank Select Left/Right: steps 1-8, 9-16, 17-24, ... -->
```

Decisions (agreed):

- **Lanes:** the 5 grid rows are 5 note lanes. Bank Select **Up/Down** pages the rows
  (lanes 1-5, 6-10, ...). Lane count is configurable (default 10 = 2 row pages).
- **Steps:** the 8 columns are 8 steps. Bank Select **Left/Right** pages the steps
  (1-8, 9-16, 17-24, ...). Pattern length is configurable (default 16 = 2 pages).
- **Playhead:** the **Clip Stop row** lights the step currently playing (green, the only
  color that row has). Dark when the playing step is on another step page.
  Track Selection keeps its normal behavior.
- **Velocity:** the original APC40 pads are **not** pressure sensitive (they always send
  `7F`), so velocity is set two ways:
  - Tap cycles a step: off -> **green** (normal) -> **amber** (accent) -> **red** (soft)
    -> off. Default velocities: normal 100, accent 127, soft 60 (configurable).
  - **Hold a step + turn a Device Control knob** for an exact velocity 1-127; the ring
    shows the value, and the pad color follows the nearest level band.
- **Clock:** follow Cakewalk. Cakewalk sends MIDI Clock + Song Position Pointer; the
  sequencer runs only while Cakewalk plays, locked to its tempo and bar position, so
  recorded notes land on the grid. Default resolution 1/16 (6 clock ticks per step).
- **Note output:** a dedicated loopMIDI cable into a Cakewalk MIDI/instrument track (arm
  it to record the pattern). Never on the Mackie Control ports.
- **Unchanged in this mode:** faders, Record Arm / Solo / Activator / Track Selection,
  Track Control knobs, transport. Meters are not drawn while the sequencer owns the grid.

Tasks:

- [ ] Research: where Cakewalk enables MIDI Clock / SPP output to a port, and confirm it
      also sends Start / Stop / Continue with the transport
- [ ] Ports: two new loopMIDI cables, e.g. `APC40-SEQ` (app -> Cakewalk notes) and
      `APC40-CLOCK` (Cakewalk -> app clock), with `SEQ_OUT_PORT` / `CLOCK_IN_PORT` in
      `.env`, opened best-effort. Separate cables so neither side reads its own traffic
- [ ] `sequencer` module (hardware-free, unit-tested): pattern model (lanes x steps x
      velocity), clock tick -> step advance, SPP positioning, Start/Stop/Continue, Note
      On/Off scheduling (fixed gate, e.g. half a step), all notes off on Stop
- [ ] Lane config: note number + MIDI channel per lane in `.env` or a YAML file; default
      GM drums on channel 10 (kick 36, snare 38, closed hat 42, open hat 46, clap 39, ...)
- [ ] Grid rendering: pad colors from the current lane page + step page; playhead on
      Clip Stop; redraw on page change and when leaving/re-entering the mode
- [ ] Input: pad press cycles the step; hold pad + Device Control knob sets velocity
      (depends on handling Mode 0 Device Control banking - see Device / plug-in mode);
      Bank Select arrows page steps/lanes instead of sending MCU cursor keys
- [ ] Page indicator: on a page change, briefly show the page number (e.g. light Clip Stop
      LED *n* for page *n*) before returning to the playhead
- [ ] Clip Stop presses in this mode: no MCU V-pot push (the row is a display); decide
      later whether they get a function
- [ ] Pattern persistence: save/load patterns to a file so they survive a restart
- [ ] Docs: sequencer section in `docs/quick-reference.md`, cables and Cakewalk clock
      setup in `docs/setup-loopmidi-and-cakewalk.md`, internals in `docs/GENERAL.md`
- [ ] Later ideas: clear pattern (e.g. Shift + Stop All Clips), per-lane mute, copy page,
      swing, per-lane step length, internal clock for jamming without the transport

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

- [x] Bank +/- (MCU 46/47) on Bank Select Left/Right and Channel +/- (48/49) on Shift +
      Left/Right (done). Bank Select arrow LEDs flash on press
- [ ] Show which bank is active (e.g. briefly on the grid); Cakewalk does not report the
      strip offset over MCU, so it would have to be tracked locally
- [x] Master fader (APC CC 14) -> MCU Pitch Bend ch 8 (done)
- [ ] **Crossfader = horizontal zoom** (APC CC 15, absolute 0-127). All Mackie Control;
      no keystrokes or mouse injection
  - [ ] Verify in Cakewalk: with MCU Zoom (note 100) on, Left/Right arrows zoom
        horizontally out/in (Cakewalk's MCU mode remaps some notes - note 89 is Loop, not
        Click - so confirm Zoom and the arrows behave as standard), and which point it
        zooms around
  - [ ] Zoom steps: slider movement -> relative steps (modular delta like the knobs);
        every N slider units (default ~8, tune so one full sweep covers the zoom range)
        send one Right (zoom in) or Left (zoom out) arrow press
  - [ ] Zoom mode handling: turn MCU Zoom on at the first movement, off after ~300 ms
        without movement, so the arrows return to normal; track the Zoom LED feedback so
        the app never toggles it the wrong way
  - [ ] Fully left = fit: at value <= 1, send one **Mackie F2** press, which the preset
        assigns to *Zoom to Fit Project Horizontally* (F1 is already *Metronome During
        Record*). Re-arm once the slider returns above ~10 so end-of-travel jitter does
        not repeat it. After a fit, moving right zooms in step by step, so slider position
        roughly tracks zoom level
  - [ ] Optional rate cap if a fast sweep makes the Track view stutter
  - [ ] Settings in `.env` (e.g. `ZOOM_STEP_UNITS`, `ZOOM_IDLE_MS`); tests; update the
        quick reference, GENERAL.md, and the F2 assignment in the setup guide
- [ ] Rewind/Forward, Cycle, Punch/Drop, Nudge, Zoom, Scrub, Markers
- [x] Bank Select arrows decided: Left/Right = bank, Shift + Left/Right = channel,
      Up/Down = Cakewalk arrow keys (done). In step-sequencer mode they will page steps
      (Left/Right) and lanes (Up/Down) instead
- [ ] Nudge + / - (100/101): unassigned; candidates are MCU Rewind/Forward or Nudge
- [ ] Tap Tempo (99): only flashes its LED; needs the keystroke bridge for real tap tempo
- [x] Cue Level knob (CC 47) -> MCU jog (CC 60): moves the playhead by the preset's Jog
      Wheel Resolution (done). Idea: Shift + Cue Level for finer steps (hold M2 = beats)
- [x] Stop pressed twice quickly -> Cakewalk Home (go to start) (done)
- [ ] Master button (80): only stays lit; candidates are select the master bus or MCU Flip.
      Note it also switches the Device Control bank to channel 8 in Mode 0
- [ ] Footswitches 1 / 2 (CC 64 / 67): unassigned; candidates are Play/Stop and Record
- [x] Removed the Rec Quantize "Cycle" LED placeholder: in Cakewalk mode LED 86 is the
      Select-navigation mode, and loop state is already on the Metronome LED
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
- [ ] **Grid modes** - step sequencer (planned in detail under Step 8), drum-pad mode (send
      notes to an instrument track) and clip-launch mode, matching the
      `docs/cakewalk-command-matrix.md` specialization. Selected with the Scene buttons.
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
