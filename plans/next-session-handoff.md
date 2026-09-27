# Next Session Handoff

Start here. State as of 2026-09-27: 236 hardware-free tests pass,
everything below "Built" is **verified on the user's hardware**, working tree clean.

## Read first

| Doc | Why |
|---|---|
| [`TODO.md`](../TODO.md) | The backlog, organized by mode (Tracking / Step Sequencer / Mixing) |
| [`docs/quick-reference.md`](../docs/quick-reference.md) | What every APC40 button does, per mode. Must stay in sync with `engine.py` |
| [`docs/GENERAL.md`](../docs/GENERAL.md) | Architecture, config keys, behavior notes, Cakewalk quirks |
| [`docs/setup-loopmidi-and-cakewalk.md`](../docs/setup-loopmidi-and-cakewalk.md) | Setup, the per-project Mackie Control preset, troubleshooting |
| [`plans/c4-surface-plan.md`](c4-surface-plan.md) | The next big feature (Mixing mode) |
| [`plans/hud-concept.md`](hud-concept.md) | HUD design (HUD is built; phase 3 = C4 param names) |

## Built (and verified on hardware)

- Mixer: 8 faders, master fader, strip buttons, Pan / Send A-B-C (sends 1-3), banking,
  Tracks/Buses toggle (Master), Track Selection (from the APC40's knob dump).
- Modes on the Scene buttons: 1 = **Tracking** (startup), 2 = Step Sequencer (not built),
  3 = **Mixing** (utility row 58-61 reserved for C4 plug-in control; does nothing yet).
- Tracking utility row: undo/redo, insert marker, marker jumps, selection start/end, loop
  and punch from selection, loop on/off, auto-punch (F2), metronome (F1).
- Playhead: Cue Level jog, Shift + Cue fine, Nudge with hold-repeat, Stop x2 = go to start;
  step sizes in `.env` (`CUE_STEP`, `SHIFT_CUE_STEP`, `NUDGE_STEP`).
- Crossfader timeline zoom (fully left = fit project).
- Shift: hold / tap = one-shot / double-tap = lock (HUD only; the APC40 Shift has no LED).
- Level meters on the clip grid, Shift + Detail View toggles Cakewalk's meters.
- On-screen HUD (separate tkinter process fed by UDP), exit animation.

## Next, in priority order

1. **Mixing mode = C4 second surface** per [`c4-surface-plan.md`](c4-surface-plan.md):
   two new loopMIDI cables (`C4_OUT_PORT` / `C4_IN_PORT`), answer the C4 handshake (it has
   no "Disable handshake"), set split/assignment at connect, `c4` module, Device knobs ->
   C4 row 1 with rings on the current bank's channel, 58-61 in Mixing = parameter page /
   next plug-in / bypass, capture C4 LCD text for the HUD. Needs the user to add cables
   and a *Mackie Control C4* surface in Cakewalk.
2. **Reconnect handling**: recover when loopMIDI mutes/drops a cable or the APC40 USB
   disconnects, without restarting the app.
3. **Readable `--monitor`**: decode notes/CCs into names ("Undo", "Marker nav + FF").
4. **Step sequencer** (Scene 2): fully specified in `TODO.md`; needs MIDI clock research.

## Critical Cakewalk / APC40 facts (learned the hard way)

The authority is Cakewalk's Mackie Control source: the **Cakewalk Control Surface SDK**,
<https://github.com/Cakewalk/Cakewalk-Control-Surface-SDK> (`Surfaces/MackieControl`).
Earlier sessions sparse-cloned it into the session scratchpad; re-clone it when needed
(`git clone --depth 1 --filter=blob:none --sparse ...` then
`git sparse-checkout set Surfaces/MackieControl`). Cite `file:line` for protocol claims.

- **Cakewalk drops real Note Off (0x80)** for its buttons. Anything it acts on at
  *release* (M1-M4 modifiers, Loop 89, cursor keys, Rewind/FF) must be released with
  **Note On velocity 0** (`mcu.cakewalk_release`), or it sticks / never toggles / repeats.
- **Cakewalk-mode button numbers** differ from the standard MCU labels: 89 = Loop,
  90 = Home, 70-73 = M1-M4, 76 = Track, 80 = Aux, 82/83 = Undo/Redo, 84-87 = Marker /
  Loop / Select / Punch navigation. There is no metronome button (use an F-key).
- **Re-pressing the active assignment button** (Pan/Send) flips the knobs to single-track
  layout, which Cakewalk never reports. Only press assignment buttons when switching
  (tracked from their LEDs).
- **All Mackie units share one static state** in Cakewalk (modifiers, selected strip);
  the C4 keeps its own assignment but shares modifiers.
- **Per-project Mackie Control preset** is required (meters, master fader = Bus, F1/F2,
  *Select highlights track*, protocol, *Disable handshake* checked). See the setup guide.
- **APC40 Generic Mode:** Track Selection sends no note (it dumps the bank's 8 Device knob
  positions); utility row and Device knobs arrive on the selected bank's channel 0-8;
  Record Arm/Solo/Activator and utility 58-61 **latch** (act on both edges); 62-65 and
  Scene buttons are momentary and the APC40 may blank their LED on release (re-assert).
  Master sends no note at all, only its channel-8 knob dump.
- **loopMIDI flood protection** mutes a cable (`[muted]`) on message bursts; only a
  loopMIDI restart clears it. Keep per-frame message budgets (`JOG_BUDGET_PER_FRAME`).

## Working conventions

- The user tests on hardware, then says "commit". Commit locally on `main` only when
  asked; do not push. Attribution line per the session's commit instructions.
- Every behavior change updates `docs/quick-reference.md` (plain language, no MCU jargon),
  `docs/GENERAL.md`, `TODO.md` (incl. the test count), and `.env.example` for new keys.
- Other Claude sessions may be editing the same checkout: check `git status` before
  editing, never stage or commit another session's files.
- Prefer Cakewalk preset settings over one-use APC40 "setup" buttons; runtime toggles the
  user flips mid-session (like meters) are fine as buttons.
- Keep button layouts "like with like" (the setter next to its on/off toggle).
