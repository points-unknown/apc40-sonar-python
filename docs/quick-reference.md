# APC40 Quick Reference

What every APC40 control does, in every mode. This is the user-facing map. For
the MIDI detail behind each action, see [`GENERAL.md`](GENERAL.md) and
[`mcu-mapping.md`](mcu-mapping.md).

> **Keep this current.** Any change to what a control does, and any new mode or Shift
> combo, updates this file in the same change. `src/apc40sonar/engine.py` is the source
> of truth. If the two disagree, this file is wrong.

**Status:** **Live** = works now. *Provisional* = placeholder behavior, will change.
`-` = does nothing yet. The **Planned** column comes from [`TODO.md`](../TODO.md) and is
not built.

Assumes `APC40_MODE=generic` (the default and the only mode tested).

## Modes at a glance

The APC40 has several independent mode layers. Each one changes a different part of the
panel.

| Mode layer | Options | Switch with | Shown by | Default | Affects |
|---|---|---|---|---|---|
| **Knob mode** | Pan, Send A, Send B, Send C | Pan / Send A / Send B / Send C buttons | Lit mode button; ring style (pan vs. fill) | Pan | Track Control knobs + rings |
| **Grid mode** | Meters, Pads | `METERS=on/off` in `.env` (restart) | Grid shows meters or stays dark | Meters | Clip grid, Clip Stop LEDs |
| **Shift layer** | Off / held / one-shot / locked | Hold, tap, or double-tap **Shift** (see Shift combos) | HUD badge `SHIFT` / `SHIFT 1x` / `SHIFT LOCK` (the APC40's Shift has no LED) | Off | Buttons that have a Shift combo; Shift + Cue Level |
| **Cakewalk meters** | Off / On | **Shift + Detail View** | Detail View flashes; grid meters appear or stop | Whatever Cakewalk had | Whether Cakewalk sends meter data |
| **Mode** | **Tracking**, **Step Sequencer**, **Mixing** | **Scene 1 / 2 / 3** | Lit Scene LED; HUD `Tracking` / `Sequencer` / `Mixing` | Tracking (always at startup) | Utility-row buttons 58-61 (see Utility row); in the Step Sequencer also the grid, Clip Stop row and Bank Select arrows (see Step sequencer) |
| **Plug-in on the Device knobs** | Any plug-in of the selected track or bus, 8 parameters at a time | Track Selection (first plug-in); in Mixing: Clip/Track (plug-in), < / > (parameters) | HUD plug-in line (pink); in Expanded, the 8 parameter names and values | The selected track's first plug-in | Device Control knobs + rings (needs the C4 surface, see Device Control knobs) |
| **Strips** | Tracks, Buses | **Master** button | HUD `Trk 9-16` / `Buses` | Tracks | What the 8 strips control: faders, strip buttons, Pan/Send knobs, meters and Track Selection |

## The three modes (Scene 1 / 2 / 3)

The workflow runs left to right: record parts, program beats, then mix. Press a Scene
button to switch; its LED stays lit. Faders, strip buttons, the Pan/Send knobs, the
Device Control knobs, transport, Cue Level, the crossfader, Stop and the Loop/Punch half
of the utility row (62-65) work the same in every mode. What changes:

| Mode | For | What changes |
|---|---|---|
| **Tracking** (Scene 1, the startup mode) | Recording and editing | Utility buttons 58-61 = **Undo / Redo, insert marker, previous / next marker**, selection start / end. The grid shows level meters |
| **Step Sequencer** (Scene 2) | Programming a drum pattern | The **grid is the pattern** and the Clip Stop row is the playhead; Bank Select arrows page steps and lanes; holding a pad lets the Device knobs set its velocity; an editor window opens. 58-61 do nothing. Needs its two cables (see Step sequencer) |
| **Mixing** (Scene 3) | Working on effects | Utility buttons 58-61 = **plug-in control**: next / previous plug-in, plug-in on/off, next / previous 8 parameters. Needs the C4 surface (see Device Control knobs). The grid shows level meters |

The HUD shows the mode (`Tracking | Trk 1-8`), and each switch toasts `Tracking mode`,
`Step sequencer mode` or `Mixing mode`. If the sequencer's cables are missing, Scene 2
stays in the current mode and the HUD says so.

## Track strips (x8, one per Cakewalk track in the current bank)

| Control | Action | LED / display | Status | Planned |
|---|---|---|---|---|
| **Fader** | Track volume | None (faders are not motorized) | **Live** | - |
| **Track Selection** | Select the track in Cakewalk (detected from the knob dump the APC40 sends on each press; needs *Select highlights track* in the Mackie Control preset) | Lit on the selected track, from Cakewalk | **Live** | - |
| **Activator** | Mute on/off (lit = **muted**, from Cakewalk) | From Cakewalk | **Live** | - |
| **Solo** | Solo on/off | From Cakewalk | **Live** | - |
| **Record Arm** | Arm on/off | From Cakewalk | **Live** (track 1 cannot arm: Cakewalk ignores it) | - |
| **Clip Stop** | **Reset this track's Track Control knob to its default**: in Pan mode re-centers the pan; in Send A / B / C mode resets that send's level to its default | Meters mode: red = this track clipped (stays lit until **Stop All Clips**). Pads mode: off | **Live** | - |

The Activator LED follows Cakewalk's mute state, so lit means muted. This is the
opposite of Ableton, where lit means active.

## Clip grid (8 x 5) and Scene column

| Control | Meters mode (default) | Pads mode (`METERS=off`) | Planned |
|---|---|---|---|
| **Grid pads** | Press does nothing. Each column is a level meter for its track: rows 5-3 green, 2 yellow, 1 red | Pad lights green while held. No action | Drum pads, clip launch |
| **Scene 1 / 2 / 3** | **Mode:** 1 = Tracking, 2 = Step Sequencer (the grid becomes the pattern; see Step sequencer), 3 = Mixing. The active mode's Scene LED is lit | Same | Scenes 4-5: free |
| **Stop All Clips** | Transport Stop + clears all clip latches + flashes Stop and Clip Stop LEDs | Stop + flash | - |

Meter scale (row: lit at): 1: 0 dB, 2: -6 dB, 3: -10 dB, 4: -20 dB, 5: -40 dB.

## Step sequencer (Scene 2)

The grid becomes a drum pattern that plays along with Cakewalk. It needs two extra
loopMIDI cables and Cakewalk's MIDI clock turned on: see the setup guide, *Step sequencer
(optional)*. Without the cables Scene 2 shows a HUD message and stays in the current mode.

> **Every project must send the clock.** In Cakewalk, *Edit > Preferences > Project >
> MIDI*: tick *Transmit MIDI Start/Continue/Stop/Clock* and select `APC40-CLOCK`. It is
> saved per project, so a new project starts without it and the pattern does not play;
> the editor window warns in amber. Set it in your template project.

**Which knob for velocity?** Any of the eight **Device Control knobs** (the bottom-right
block of knobs): hold the pad and turn whichever is closest.

```text
            step 1 ... step 8        (one page of 8 steps)
grid row 1  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 1  (kick)
grid row 2  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 2  (snare)
grid row 3  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 3  (closed hi-hat)
grid row 4  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 4  (open hi-hat)
grid row 5  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 5  (clap)
Clip Stop   [ ][ ][*][ ][ ][ ][ ][ ]  the step playing now
```

| Control | Action | LED | Status |
|---|---|---|---|
| **Grid pad** (tap) | Cycle the step: off -> **green** (normal, velocity 100) -> **amber** (accent, 127) -> **red** (soft, 60) -> off | Step color | **Live** |
| **Grid pad** (hold 1 s on a lit step) | Turn the step **off** (no need to cycle through) | Goes dark at the 1 s mark | **Live** |
| **Grid pad** (hold) + **any Device Control knob** | Set the held step's exact velocity (1-127). Several pads can be held at once | The pad shows the nearest color; the knob's ring shows the value; the HUD shows `Velocity N` | **Live** |
| **Clip Stop row** | Display only: the step playing now (dark while stopped, or when the playing step is on another page). Pressing does nothing | Green | **Live** |
| **Bank Select Left / Right** | Previous / next page of **steps** (1-8, 9-16, ...) | For 0.6 s the Clip Stop row shows the page number: LED *n* = page *n* | **Live** |
| **Bank Select Up / Down** | Previous / next page of **lanes** (1-5, 6-10) | Same, but blinking | **Live** |

- **Editor window:** entering Scene 2 opens *APC40 Step Sequencer* on screen; leaving
  Scene 2 closes it. It shows the whole pattern (up to 64 steps x 32 lanes), the playing
  step (white box) and, in blue, the 8 x 5 part the APC40 shows. Click a cell = same as a
  pad tap; right-click = clear; mouse wheel = velocity +/-5 (Shift +/-1). Click a step
  number or lane number to move the APC40's view there. Edit a lane's name and note in
  place; **right-click a lane** to move it up / down, add a lane or remove it.
- **Toolbar:** **Steps** (pattern length), **Paste from Sonar** and **Export .mid** (with
  the last bar count, 4 at first). Everything else is in the menus:

  | Menu | Items |
  |---|---|
  | **File** | Paste from Sonar (Ctrl+V), Import .mid... (Ctrl+O), Export .mid... (Ctrl+E, asks how many bars), Open patterns folder |
  | **Pattern** | Add lane, Clear all steps..., Length (8-64 steps), MIDI channel (1-16) |
  | **Drum map** | The built-in maps (General MIDI 10 / 16 lanes, Addictive Drums 2 16 / 32 lanes) and your saved ones; Save current lanes as map..., Import map..., Export map... |
  | **View** | Always on top, Playhead lead... |

- **Export .mid** writes the pattern, repeated to fill the bars, to
  `patterns/pattern-<date>-<time>.mid` and opens Explorer with the file selected: drag it
  onto a Cakewalk track to get regular MIDI notes (one track).
- **Import .mid** replaces the steps with a MIDI file's notes: starting at the bar of its
  first note, snapped to sixteenths, up to 64 steps. A clip that repeats the same 1 or 2
  bars comes in as just that cycle. Lanes keep their names; notes with no lane get a new
  one. Copy from Sonar starting on a bar line, or everything shifts.
- **Paste from Sonar** takes a MIDI clip you copied in Sonar (Ctrl+C) and loads it like
  Import. There is no copy the other way (Sonar only pastes its own copies): use Export.
- **Playhead lead** (View menu): if the Clip Stop row and the white box lag behind what
  you hear, raise it until they line up; lower it if they run early. Default 40 ms
  (`SEQ_DISPLAY_LEAD_MS`); your value is remembered (`patterns/settings.json`). It only
  moves the display, never the notes.
- **Drum maps** (the lane list: note, name, channel of each lane, without the steps):
  picking one keeps every row's steps and changes what each row plays; a shorter map leaves
  the extra rows alone. Saved maps live in `patterns/drum-maps/`; Import / Export map read
  or write a map file anywhere, for example to share it.
- The pattern **saves itself** (`patterns/current.json`) and comes back when the app
  restarts.
- The pattern plays only while Cakewalk plays and follows its tempo and position, so
  recording on the drum track captures exactly what you hear.
- Default lanes (General MIDI drums, channel 10): kick 36, snare 38, closed hat 42, open
  hat 46, clap 39, rim 37, low tom 45, mid tom 47, high tom 50, crash 49. Change them with
  `SEQ_NOTES` / `SEQ_CHANNEL`; the pattern length is `SEQ_STEPS` (default 16). These only
  shape a brand-new pattern; after that, edit in the window.
- Faders, strip buttons, Track Control knobs, transport, Cue and the crossfader work as
  usual, and the Device Control knobs still control the plug-in whenever no pad is held.
  The meters leave the grid while the sequencer owns it and come back on Scene 1 / 3.

## Knobs

### Track Control knobs (top right, x8)

| Knob mode | Knobs control | Rings show | Status |
|---|---|---|---|
| **Pan** | Track pan | Pan style, centered at startup; then Cakewalk's value | **Live** |
| **Send A** | Level of each track's **send 1** | Fill style, Cakewalk's value | **Live** |
| **Send B** | Level of each track's **send 2** | Fill style, Cakewalk's value | **Live** |
| **Send C** | Level of each track's **send 3** | Fill style, Cakewalk's value | **Live** |

Only the first three sends on a track are reachable. To control a later send, move it into
one of the top three slots in Cakewalk. On a track with fewer sends, the knob stays on its
last send.

### Device Control knobs (bottom right, x8)

| When | Knobs control | Rings show | Status |
|---|---|---|---|
| Every mode, with the C4 surface set up | **8 parameters of the selected track's plug-in**. Pick the track with Track Selection; on **Buses** (Master) they control the selected bus's plug-in. The Track Control knobs stay on Pan/Sends | The parameter values from Cakewalk; **off** = no parameter on this knob | **Live** (verified: knobs, plug-in stepping; *paging and on/off need a hardware test*) |
| Step Sequencer, while a pad is held | That step's velocity (see Step sequencer) | The velocity | **Live** |
| Without the C4 surface (cables missing or `C4=off`) | Nothing | Centered, pan style (startup) | `-` |

The plug-in control needs two more loopMIDI cables and a second Cakewalk surface: see the
setup guide, *Plug-in knobs (optional)*.

- **Which plug-ins:** every effect in the track's FX rack, in order, and the
  **ProChannel** modules (EQ, compressor, Tube, ...), which Cakewalk lists first. *Exclude
  filters from plug-ins* on the main Mackie Control page should leave the ProChannel out
  (not tested).
- **Choosing the plug-in and the 8 parameters:** in **Mixing** mode (Scene 3) with the
  utility row: **Clip/Track** = next plug-in (Shift = previous), **< / >** = previous /
  next 8 parameters (Shift = by 1), **Device On/Off** = the plug-in's on/off switch. See
  Utility row. In the other modes the knobs keep the last choice.
- **Paging:** the first page is parameters 1-8, then 9-16, and so on; the HUD toasts
  `Parameters 9-16`. Paging stops at the plug-in's last parameter (`No more parameters`)
  and at its first (`First parameters`). With Shift the window moves by one, for example to
  get parameters 2-9.
- **Connecting:** when the app starts (and when Cakewalk reloads the surface) it sets up
  the C4 for about a second; the HUD shows `connecting to Cakewalk's C4 surface...`, then
  toasts `Plug-in control ready`. The knobs do nothing until then. Cakewalk only talks to
  the C4 with a project open.
- **Picking a track** (Track Selection) or switching Tracks/Buses (Master) jumps to the
  track's **first plug-in, first 8 parameters**; the HUD's plug-in line names them, e.g.
  `FX 1: Sonitus EQ  (Track 3: "Vox")` (`C4_RESET_ON_SELECT=off` keeps the position
  instead).
- **On/off switch skipped:** many plug-ins list their on/off switch first (ProChannel
  modules call it *Enable*, Cakewalk's effects *Bypass*; its value reads On or Off). Then
  the knobs start at the parameter after it, so all 8 are real controls. In Mixing,
  **Device On/Off** presses the switch. The HUD shows its state on the plug-in line, e.g.
  `[Bypass: Off]`.
- **Speed:** turn slowly for fine steps (about 0.5 % of the range per click), fast for
  bigger ones. `C4_KNOB_STEP_LIMIT` (1-15, default 3) caps the speed.
- Clicking a track with the mouse in Cakewalk also moves the knobs to that track, but
  without the jump to the first plug-in.
- After switching to **Buses**, the knobs first land on the bus with the same number as the
  last selected track (Cakewalk shares the selection number). Press a Track Selection
  button to pick the bus.

### Other continuous controls

| Control | Action | Status | Planned |
|---|---|---|---|
| **Master fader** | Master bus volume (set Cakewalk's Mackie *Master Fader* to Bus + Master bus; see setup guide) | **Live** | - |
| **Crossfader** | **Horizontal zoom**: slide right = zoom in, left = zoom out (one step per ~6/127 of travel); **fully left = fit project**. Cakewalk's Track view needs keyboard focus | **Live** | - |
| **Cue Level** | Move the playhead, clockwise = forward: **1 beat** per detent (`CUE_STEP`). **Shift + Cue Level** = fine: **30 ticks** (1/32 of a beat) per detent (`SHIFT_CUE_STEP`) | **Live** | - |
| **Footswitch 1 / 2** | - | `-` | Not planned |

## Knob mode buttons

| Button | Action | LED | Status |
|---|---|---|---|
| **Pan** | Knob mode = Pan: the Track Control knobs set each track's pan | Only the active mode button is lit | **Live** |
| **Send A / B / C** | Knob mode = send 1 / 2 / 3 level. Pressing the lit one again re-selects its send | Only the active mode button is lit | **Live** |

## Utility row (under the Device Control knobs)

These buttons work, and their LEDs show, whichever track (or Master) is selected. The
row groups **Loop** (62-63) and **Punch** (64-65): the "from selection" setter next to its
on/off toggle. In Mixing, 58-61 choose what the Device Control knobs control (they need
the C4 surface; without it the HUD toasts `Plug-in control: no C4 surface`). In the Step
Sequencer, 58-61 do nothing.

| Button | Tracking (Scene 1) | Mixing (Scene 3) | Shift + button (both modes) | LED |
|---|---|---|---|---|
| **Clip/Track** (58) | **Undo** | **Next plug-in** on the selected track, starting on its first parameters; after the last it goes back to the first | Tracking: **Redo**. Mixing: **previous plug-in** | Mixing: flashes |
| **Device On/Off** (59) | **Insert marker** at the playhead | **Plug-in on/off**: presses the plug-in's on/off switch (*Enable* / *Bypass*), from any parameter page; the HUD toasts the new state, e.g. `Bypass: On`. Plug-ins without a switch: HUD says so | - | Mixing: flashes |
| **Left / Right arrow** (60/61) | **Previous / next marker** | **Previous / next 8 parameters** of the plug-in; stops at its first and last (HUD: `First parameters` / `No more parameters`) | Tracking: **go to selection start / end**. Mixing: **parameters back / forward by 1** | Mixing: flashes |
| **Detail View** (62) | **Loop <- selection**: loop points = the current selection | Same | **Cakewalk meters on/off** | Flashes on the meters toggle |
| **Rec Quantize** (63) | **Loop on/off** (playback repeats between the loop points) | Same | - | **Lit while loop is on**, from Cakewalk |
| **MIDI Overdub** (64) | **Punch <- selection**: punch points = the current selection | Same | - | - |
| **Metronome** (65) | **Auto-punch on/off** (Mackie F2 in the preset) | Same | **Metronome during record on/off** (Mackie F1) | None: Cakewalk reports neither state |

Set the selection with **Shift + Nudge - / +** (selection start / end = playhead), then
use Loop <- selection or Punch <- selection.

## Transport and navigation

| Button | Action | LED | Status | Planned |
|---|---|---|---|---|
| **Play** | Play | From Cakewalk | **Live** | - |
| **Stop** | Stop. **Press twice quickly** (within 0.4 s) to also return to the start of the project | From Cakewalk | **Live** | - |
| **Record** | Record | From Cakewalk | **Live** | - |
| **Bank Select Left / Right** | Move the 8-track window by **8 tracks** (tracks 1-8 -> 9-16 ...). Step Sequencer: page the steps | Flashes on press | **Live** | - |
| **Shift + Bank Select Left / Right** | Move the 8-track window by **1 track** | Flashes on press | **Live** | - |
| **Bank Select Up / Down** | Cakewalk arrow key Up / Down. Step Sequencer: page the lanes | Flashes on press | **Live** | - |
| **Shift** | Modifier: hold, tap (one-shot) or double-tap (lock); see Shift combos | No LED on the APC40; shown in the HUD | **Live** | - |
| **Tap Tempo** | - (LED flash only) | Flash | *Provisional* | Tap tempo keystroke (needs keystroke bridge) |
| **Nudge - / +** | Move the playhead back / forward **1 measure** per press (`NUDGE_STEP`); **hold** to keep moving (repeats every `NUDGE_REPEAT_MS` after 0.4 s) | - | **Live** | - |
| **Shift + Nudge - / +** | **Selection start / end = playhead** | - | **Live** | - |
| **Master** (Track Selection) | **Toggle the 8 strips between Tracks and Buses** (faders, strip buttons, knobs, meters and Track Selection then act on buses) | The APC40 lights it itself (Track Selection radio group); the HUD shows `Buses` | **Live** | - |

## Shift combos

Three ways to use **Shift**:

| You do | Effect | HUD |
|---|---|---|
| **Hold** Shift and press a button | That press is shifted | `SHIFT` |
| **Tap** Shift | The **next button press** is shifted, then Shift turns off. Any button uses it up, even one without a Shift combo. Expires after 3 s (`SHIFT_ONESHOT_MS`) | `SHIFT 1x` |
| **Double-tap** Shift (within 0.4 s) | **Locked**: every button press is shifted until you tap Shift again | `SHIFT LOCK` |

Knobs (Shift + Cue Level) follow a **held or locked** Shift only; a tapped one-shot waits
for a button. Buttons without a combo do their normal action while shifted.

| Combo | Action | Status |
|---|---|---|
| **Shift + Detail View** | Toggle Cakewalk Mackie Control meters on/off (sends M2 + Name/Value; steps twice if needed) | **Live** |
| **Shift + Bank Select Left / Right** | Move the 8-track window by 1 track | **Live** |
| **Shift + Metronome** | Metronome **during record** on/off (sends Mackie F1; the preset assigns F1 to *Metronome During Record*) | **Live** |
| **Shift + Clip/Track** | Redo (Tracking); previous plug-in (Mixing) | **Live** |
| **Shift + Left / Right arrow** | Go to selection start / end (Tracking); parameters back / forward by 1 (Mixing) | **Live** |
| **Shift + Nudge - / +** | Selection start / end = playhead | **Live** |

Free for future combos: Shift + Device On/Off, Shift + Rec Quantize, Shift + MIDI
Overdub, and the strip buttons (e.g. Shift + Mute = clear all mutes).

## On-screen HUD

The APC40 has no display, so the app shows a small always-on-top window with what the panel
is doing and what Cakewalk reports. It opens with the app and closes with it. Turn it off
with `--no-hud`, or `HUD=off` in `.env`. Clicking it never takes keyboard focus from
Cakewalk.

```text
 Expanded only (grows to the left)                         Compact (always)
+----------------------------------------------------+  +--------------------------------------------+
| DecyTm LwDmpR LwFrqC HDmpRt HFrqCt Distnc Dimnsn . |  | PAN  Mixing | Trk 1-8  Sel 1 Audio  > PLAY |
| 1.1Sec 0.80x  160 Hz 0.48x  5243Hz 4.06Mt 2.00   . |  | 32.3.041  Assign PN  LOOP ZOOM ... [toast] |
| Audio  Track2 ...                                  |  | (status line)                              |
| -- meters, R/S/M dots --                           |  | FX 5: TrueVerb Mono [Bypass: Off] (Trk 1)  |
+----------------------------------------------------+  +--------------------------------------------+
```

### Compact (the main HUD)

| Where | Shows |
|---|---|
| Large, colored (top left) | The Track Control knob mode: `PAN` (amber), `SEND A (1)` (cyan), `SEND B (2)` (violet), `SEND C (3)` (green) |
| `Tracking \| Trk 9-16` | The mode, then the tracks on the 8 strips, or `Buses` after Master. `Trk ?` until the first Track Selection press; `Trk ~17-24` = estimated after Bank/Channel moves, confirmed by the next select |
| `Sel 12 Vocals` | The selected track's number and name |
| `STOP` / `PLAY` / `REC` | Cakewalk's transport |
| Time | Bars.beats.ticks (or SMPTE), from Cakewalk |
| `Assign PN` | Cakewalk's assignment display (`PN` = pan, `SE` = sends) |
| Badges | **LOOP** (loop on), **ZOOM** (crossfader zoom active), **METERS** (Cakewalk sends meters), **SHIFT** / **SHIFT 1x** / **SHIFT LOCK** (held / one-shot / locked). Dim = off |
| Toast (right) | About a second of text for each action the panel has no light for: `Undo`, `Redo`, `Marker inserted`, `Next marker`, `Loop <- selection`, `Auto-punch toggled`, `Tracks` / `Buses`, `Send B`, `Bank >`, `Go to start`, `Zoom: fit project`, `Tracking mode`, `Next plug-in`, `Parameters 9-16`, `Bypass: On`, `Velocity 96`, `Plug-in control ready`, Cakewalk's own `Track 12: "Vocals"`, ... |
| Status line | Empty when all is well. `no link to apc40sonar` (the app is not running), `Cakewalk idle` (no feedback lately), `no Cakewalk feedback port` / `no Cakewalk control port` (a loopMIDI cable is missing), red `Strip layout!` (Cakewalk flipped the knobs to one track) |
| Plug-in line (pink) | What the Device Control knobs control: `FX 5: TrueVerb Mono  [Bypass: Off]  (Track 1: "Audio")`. `[...]` is the plug-in's on/off switch, when it has one; `(empty slot)` = no plug-in there; `connecting to Cakewalk's C4 surface...` while it sets up. Hidden without the C4 surface |

All text has a fixed width and long text is cut with "…", so the HUD never changes size.

### Expanded

Right-click > **Expanded** (or `HUD_LAYOUT=expanded`) adds two rows to the **left** of the
compact HUD, so the window stays one short band:

- **Parameters** (with the C4 surface): the names and current values of the 8 parameters
  on the Device Control knobs, knob 1 on the left.
- **Strips:** per track strip, the name (a knob's value briefly replaces it, in white),
  Cakewalk's second LCD line, R / S / M dots (record, solo, mute), and a level meter with a
  clip mark. The selected strip is highlighted.

### Moving it

- **Drag** it anywhere with the left mouse button. It remembers the spot (in
  `.hud-position.json` next to `.env`) and keeps its **right edge** there, so Expanded
  grows to the left.
- **Right-click** menu: Compact / Expanded, Opacity, **Reset position**, Quit HUD.
- Without a dragged spot it sits in the `HUD_POSITION` corner (default top right),
  `HUD_MARGIN` pixels in (default `50,12`: 50 from the right, 12 from the top).
- If the remembered spot is on a monitor that is no longer there, the HUD comes back to its
  default corner. You can also start the app with `uv run apc40sonar --reset-hud-position`.

### Settings (`.env`)

| Key | Default | Meaning |
|---|---|---|
| `HUD` | `on` | Open the HUD with the app (`--hud` / `--no-hud` override it) |
| `HUD_LAYOUT` | `compact` | `compact` or `expanded` |
| `HUD_POSITION` | `top-right` | Corner: `top-left`, `top-right`, `bottom-left`, `bottom-right`, or `x,y` |
| `HUD_MARGIN` | `50,12` | Gap from that corner in pixels: sideways, then up/down |
| `HUD_MONITOR` | `0` | Which monitor (0 = the main one) |
| `HUD_OPACITY` | `0.85` | 0.2 (see-through) to 1.0 (solid) |
| `HUD_TOPMOST` | `on` | Keep it above other windows |
| `HUD_CLICK_THROUGH` | `off` | Clicks go through it to Cakewalk (it can then only be placed with the settings) |
| `HUD_TOAST_MS` | `1200` | How long a toast stays |
| `HUD_LCD` | `on` | Read Cakewalk's display text (track names, values, messages) |

To start a HUD by hand for an app that is already running:
`uv run python -m apc40sonar.hud`.

## Playhead step sizes

Set in `.env` as `<count> <unit>`, unit = `measure`, `beat`, `tick` (1/960 beat) or
`jog` (the Mackie preset's *Jog Wheel Resolution*). Measure and beat steps land on the
grid. The count is 1-48: each unit is one MIDI message, and bigger values
(or spinning very fast) could flood the loopMIDI cable.

| Key | Control | Default |
|---|---|---|
| `CUE_STEP` | Cue Level, per detent | `1 beat` |
| `SHIFT_CUE_STEP` | Shift + Cue Level, per detent | `30 tick` (1/32 beat) |
| `NUDGE_STEP` | Nudge - / +, per press and per repeat while held | `1 measure` |
| `NUDGE_REPEAT_MS` | Repeat interval while Nudge is held | `150` |

## Exit

On Ctrl+C the grid fills red and drains away top to bottom, then the whole panel
goes dark: a dark APC40 means the app is not running.

## Startup state

After the lightshow the panel rests in:

- Knob mode **Pan**, Pan button lit, Track Control rings centered
- Device Control rings centered (pan style), until the C4 surface connects (about a
  second, with a project open); then they show the selected track's first plug-in (HUD
  toast `Plug-in control ready`)
- The HUD in its default corner, or where you last dragged it
- **Tracking** mode, **Scene 1** lit; strips on Tracks
- Grid dark until Cakewalk sends meters or LED state
