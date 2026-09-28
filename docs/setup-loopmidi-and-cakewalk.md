# Setup: APC40 + Cakewalk by BandLab

Get the original Akai APC40 driving Cakewalk in about ten minutes. Everything is a
one-time setup except the three-step [daily startup](#daily-startup).

## How it fits together

```text
Akai APC40 <--USB--> apc40sonar (Python) --APC40-IN-->  Cakewalk "Mackie Control" surface
                              ^------------APC40-OUT---'
```

- **loopMIDI** provides two virtual MIDI cables. That is its only job.
- **apc40sonar** is the only program that opens the physical `Akai APC40`. It translates
  APC40 messages into Mackie Control (MCU) and translates Cakewalk's MCU feedback back into
  APC40 LEDs and rings.
- **Cakewalk** never sees the APC40. It sees a standard Mackie Control surface.

| Port | What it is | Opened by apc40sonar as | Cakewalk Mackie Control |
|---|---|---|---|
| `Akai APC40` | Physical USB device | read + write | **not used** (leave it disabled) |
| `APC40-IN` | loopMIDI cable | write (app -> Cakewalk) | **Input** port |
| `APC40-OUT` | loopMIDI cable | read (Cakewalk -> app) | **Output** port |

The names are from Cakewalk's point of view: Cakewalk reads from `APC40-IN` and writes to
`APC40-OUT`.

## One-time setup

### 1. loopMIDI: create the two cables

1. Install loopMIDI from <https://www.tobias-erichsen.de/software/loopmidi.html>.
2. **Reboot** if this is the first time loopMIDI has been installed. Its driver
   does not expose new ports to Windows until after a restart.
3. Open loopMIDI, type `APC40-IN` in the name box and click **+**. Repeat for `APC40-OUT`.
4. Turn on loopMIDI's **Autostart** option (tray icon menu) so it starts with Windows. The
   cables only exist while loopMIDI is running.

### 2. apc40sonar: install and configure

You need [uv](https://docs.astral.sh/uv/), which also installs Python 3.14 for you:

```bat
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then, from the repository root:

```bat
uv sync
copy .env.example .env
```

Plug in the APC40, close any other app that might be using it (including Cakewalk), and
check the ports:

```bat
uv run apc40sonar --list-ports
```

The end of the output should show three `[OK  ]` lines:

```text
Configured ports:
  [OK  ] apc40   (read+write) 'Akai APC40' (out: index 1, in: index 0)
  [OK  ] mcu_out (app->CW)     'APC40-IN' (out: index 2)
  [OK  ] mcu_in  (CW->app)     'APC40-OUT' (in: index 1)
```

If any line says `FAIL`, look at the port list printed above it. Windows sometimes
reports a slightly different name (for example with a number added). Copy the exact name
into `.env` (`APC40_PORT`, `MCU_OUT_PORT`, `MCU_IN_PORT`) and run the check again.

Optional check of the APC40 link on its own (loopMIDI not needed):

```bat
uv run apc40sonar --lightshow
```

### 3. Cakewalk: add the Mackie Control surface

Start apc40sonar first (see [daily startup](#daily-startup)) so the APC40 port is already
in use, then open Cakewalk.

1. **`Edit > Preferences > MIDI > Devices`**
   - Inputs: check **`APC40-IN`**. Leave **`Akai APC40`** unchecked.
   - Outputs: check **`APC40-OUT`**. Leave **`Akai APC40`** unchecked.
   - Click **Apply**.
2. **`Edit > Preferences > MIDI > Control Surfaces`**. Click the **Add** (+) button:
   - Controller/Surface: **Mackie Control**
   - Input Port: **`APC40-IN`**
   - Output Port: **`APC40-OUT`**
   - Click **OK**.
3. On the same page, set:
   - *Control Strips Visible In*: **Console View** (or **All Strips**)
   - *Refresh Frequency*: **50-75 ms**
   - Leave **ACT** off for this surface.
4. Click **Apply** and close Preferences.

Cakewalk only lists a port under Control Surfaces after it has been enabled under
Devices. If the ports are missing from the dropdowns, go back to step 1.

These Preferences settings are global: Cakewalk keeps them for every project.

### 4. Cakewalk: Mackie Control surface settings (save as a preset)

The Mackie Control surface has its own settings page, and **its settings are stored per
project**, not globally. Some of Cakewalk's defaults are wrong for the APC40, so every
project needs these settings. Set them once, then save them as a preset and in your
project template (see below) so you never have to look for them again.

*Master Fader*, *F1*, *F2*, *Jog Wheel Resolution*, *Select highlights track*, *Protocol* and
*Disable handshake* are set-and-forget. *Meters* is
different: it is a workflow choice you can flip at any time from the APC40 with
**Shift + Detail View** (see [Meters on or off](#meters-on-or-off) below), so the preset
only decides how each project **starts**.

Open the page with **`Utilities > Mackie Control`** (with more than one surface it is
listed as *Mackie Control - 1* and so on).

| Setting | Where on the page | Set to | Cakewalk default | What goes wrong otherwise |
|---|---|---|---|---|
| **Meters** (starting state) | *Options* group, **Meters:** dropdown | **Signal LEDs** to start with grid meters on (*Signal LEDs + Meters* is the same for the APC40), or **Off** to start with them off | Off | Nothing breaks either way. Off means Cakewalk sends no meter data and the grid stays dark until you press **Shift + Detail View** |
| **Master Fader** | *Master Fader* group (bottom left), two dropdowns | First: **Bus**. Second: your **Master** bus | *Master*, first strip | The APC40 master fader moves Cakewalk's hidden **hardware-output** strip instead of the Master bus, so it seems to do nothing |
| **F1** (metronome) | *Function Buttons* group, **F1:** dropdown | **Metronome During Record** (the list is Cakewalk's full command list; pick the *Metronome During Record* entry, not *During Playback*) | Unassigned | **Shift + Metronome** on the APC40 does nothing. Cakewalk's Mackie Control has no metronome button of its own, so the app sends F1 |
| **F2** (auto-punch) | *Function Buttons* group, **F2:** dropdown | Cakewalk's **auto-punch** on/off command | Unassigned (older presets may have *Zoom to Fit Project Horizontally* here; the crossfader's fit no longer needs it) | The APC40 **Metronome** button (auto-punch) does nothing |
| **Jog Wheel Resolution** | *Jog Wheel Resolution* group | Any | Measures | Nothing. The APC40's playhead step sizes are set in `.env` (`CUE_STEP`, `SHIFT_CUE_STEP`, `NUDGE_STEP`); this only applies to a step set to unit `jog` |
| **Select highlights track** | *Options* group | **Checked** | Unchecked | The APC40 **Track Selection** buttons only move the Mackie surface's internal focus; the track is not selected in Cakewalk. Leave *Double-click to select* unchecked |
| **Protocol** | *Protocol* group | **Mackie Control Universal (Cakewalk/SONAR Mode)** | Same (leave it) | *Universal Mode* renumbers buttons and ignores the modifier keys; *HUI* and *Cubase Mode* are different protocols |
| **Disable handshake** | *Options* group | **Checked** | Checked (leave it) | apc40sonar does not answer Cakewalk's Mackie handshake, so with this unchecked Cakewalk ignores every APC40 button and fader |

Everything else on the page can stay at its default.

> **"Master" means two different things.** In the *Master Fader* type dropdown,
> *Master* is Cakewalk's hardware-output strip. The bus called "Master" in your project
> is a normal **Bus**, so choose **Bus** and then pick it by name in the second dropdown.

**Save the settings so they stick:**

1. **Preset.** Use the preset box at the top of the Mackie Control window: type a name
   such as `APC40` and click the save (disk) icon. In any project, pick `APC40` from that
   box to apply all the settings at once.
2. **Project template.** Apply the preset in an empty project and save it with
   **`File > Save As`**, file type **Template**. New projects made from that template
   start with the right settings. Existing projects still need the preset applied once
   each.

### 5. Check that it works

- Move APC40 fader 1. Cakewalk track 1's volume follows.
- Move the APC40 master fader. Cakewalk's **Master** bus volume follows. (If not, check
  the *Master Fader* setting in step 4.)
- Mute a track with the mouse. The matching APC40 Activator LED changes.
- Press Play on the APC40. Cakewalk starts playing. With audio playing, the clip grid
  shows level meters. (If it stays dark, press **Shift + Detail View** to turn meters on.)
- The HUD window shows `Tracking | Trk ?`, and **Scene 1** is lit. Press a **Track
  Selection** button: Cakewalk selects that track and the HUD shows its number and name.
- Press **Metronome** (auto-punch) and **Shift + Metronome** (metronome): both toggle in
  Cakewalk's Control Bar. (If not, check *F2* / *F1* in step 4.)

What every button does: [`quick-reference.md`](quick-reference.md).

### 6. Step sequencer (optional)

Scene 2 turns the grid into a drum pattern. It needs two more cables and Cakewalk's MIDI
clock. Skip this section if you do not use it; the rest of the app works without it.

1. **loopMIDI:** add two cables, `APC40-SEQ` (the app's notes to Cakewalk) and
   `APC40-CLOCK` (Cakewalk's clock to the app). Separate cables keep each side from
   reading its own messages.
2. **Cakewalk, Edit > Preferences > MIDI > Devices:** tick `APC40-SEQ` under **Inputs**
   and `APC40-CLOCK` under **Outputs**. Leave `APC40-SEQ` as an output and `APC40-CLOCK`
   as an input unticked. Then **close and reopen Cakewalk**: changing MIDI devices while
   it runs disconnects the Mackie Control surface (the APC40 stops controlling Cakewalk,
   even after undoing the change) until Cakewalk restarts. After the restart, check that
   *Preferences > MIDI > Control Surfaces* still shows `APC40-IN` / `APC40-OUT`.
3. **Cakewalk, Edit > Preferences > Project > MIDI (in EVERY project):** tick **Transmit
   MIDI Start/Continue/Stop/Clock** and select **only** `APC40-CLOCK` under **MIDI Sync
   Output Ports** (clock sent to `APC40-IN` or `APC40-OUT` floods the Mackie cable).
   If there is a Song Position Pointer option, tick it too, so the pattern lines up when
   you start from the middle of the song.

   > **This is a per-project setting, and you must set it by hand.** A new project starts
   > without it, and then the sequencer silently does nothing: the pads light, but Play
   > plays no pattern. Set it in your **template project** so new projects inherit it.
   > If you forget, the editor window says so (in amber) after 1.5 s of playing without a
   > clock. Cakewalk stores the port by number, not name, so check it again if you add or
   > remove MIDI devices.
4. **A drum track:** add a MIDI or instrument track (any drum synth that uses General MIDI
   notes), set its **input** to `APC40-SEQ` (channel 10, or Omni) and turn on input echo
   to hear it. Arm it to record the pattern.
5. Run `uv run apc40sonar --list-ports`: both show `OK` under *Step sequencer ports*.

Press **Scene 2**: the editor window opens. Tap a few pads (or click cells) and press
Play. The Clip Stop row and the window's white box follow the playing step. To get the
pattern into Cakewalk as regular MIDI notes, either record the drum track (turn on its
Input Quantize at 1/16 for exact timing) or click **Export .mid** and drag the file onto
a track.

## Daily startup

1. **loopMIDI** is running (automatic if Autostart is on).
2. **Start apc40sonar.** Double-click `run-apc40-sonar.cmd` in the repository root, or
   run `uv run apc40sonar`. Wait for the lightshow to finish and `running - press Ctrl+C
   to stop` to appear. The HUD window opens; the APC40 starts in **Tracking** mode
   (Scene 1 lit). Leave the console window open.
3. **Open Cakewalk.**

To stop, press Ctrl+C in the apc40sonar window: the grid drains red and the panel goes
dark (a dark APC40 means the app is not running). A desktop shortcut to
`run-apc40-sonar.cmd` makes step 2 a single click.

Useful options: `--no-show` skips the lightshow and `--monitor` prints every MIDI
message in both directions. [`GENERAL.md`](GENERAL.md#runtime-modes) lists them all.

## Meters on or off

The clip grid shows a level meter per track while Cakewalk sends meter data. Whether it
does is Cakewalk's *Meters* setting, and you can switch it without opening any dialog:

- **Shift + Detail View** on the APC40 turns Cakewalk's meters **on** if they are off,
  and **off** if they are on. The Detail View LED flashes to confirm; within half a
  second the grid meters appear or fall dark.
- Use it whenever the workflow calls for it, for example meters on while mixing and off
  while programming or editing. The change is saved with the project like any other
  Mackie Control setting.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Scene 2: pads and editor work, but Play plays no pattern and the Clip Stop row stays dark | This project does not send MIDI clock (a per-project setting) | In this project: Edit > Preferences > Project > MIDI, tick **Transmit MIDI Start/Continue/Stop/Clock**, select only `APC40-CLOCK`. Save it in your template |
| `error: cannot open APC40 port` | Another app holds the APC40 | Close Cakewalk (or uncheck `Akai APC40` in its MIDI Devices), MIDI-OX, Ableton, etc., then start apc40sonar again |
| `APC40-IN` / `APC40-OUT` shows `FAIL` or `MISSING` | loopMIDI not running, the cable wasn't created, or Windows renamed it | Start loopMIDI and check both cables are listed; copy the exact names from `--list-ports` into `.env`. Reboot after a fresh loopMIDI install |
| loopMIDI lists the cables but `--list-ports` does not | Driver not registered yet | Reboot with loopMIDI set to autostart, then check again |
| Lightshow runs but Cakewalk does nothing | Surface missing or ports swapped | Check that Mackie Control has Input `APC40-IN` and Output `APC40-OUT` |
| Cakewalk responds but LEDs don't follow | `APC40-OUT` not enabled as a Cakewalk output | Enable it under MIDI Devices, then re-check the surface's Output port |
| A button toggles twice per press | APC40 also set up directly in Cakewalk | Remove any APC40 device/surface in Cakewalk. Only the Mackie Control surface on the loopMIDI cables should remain |
| Grid meters stay dark with audio playing | Cakewalk's **Meters** is Off in this project | Press **Shift + Detail View** on the APC40. `--monitor` then shows `mcu: [208, ...]` lines |
| Master fader moves nothing (but `--monitor` shows `mcu: [232, ...]` echoes) | *Master Fader* is on type *Master* (hardware outputs), Cakewalk's default | Apply your `APC40` preset, or set **Master Fader** to **Bus** + your Master bus ([step 4](#4-cakewalk-mackie-control-surface-settings-save-as-a-preset)) |
| Track Selection buttons light but the track is not selected in Cakewalk | *Select highlights track* is unchecked (Cakewalk's default) | Check it ([step 4](#4-cakewalk-mackie-control-surface-settings-save-as-a-preset)) and re-save the preset |
| Every APC40 button and fader is ignored, but LEDs still follow Cakewalk | **Disable handshake** is unchecked | Check it again ([step 4](#4-cakewalk-mackie-control-surface-settings-save-as-a-preset)) |
| Shift + Detail View does nothing (log: "sent no meters") | *Protocol* is not *Cakewalk/SONAR Mode* | Set it back ([step 4](#4-cakewalk-mackie-control-surface-settings-save-as-a-preset)) |
| Everything stopped responding; loopMIDI shows `APC40-IN` (or `-OUT`) as `[muted]` | loopMIDI's flood protection muted the cable after a burst of messages | Quit and restart loopMIDI (or remove and re-add the cable), then restart Cakewalk and apc40sonar |
| **Metronome** (auto-punch) or **Shift + Metronome** does nothing | *F2* / *F1* not assigned in this project's Mackie Control settings | Apply your `APC40` preset, or set them ([step 4](#4-cakewalk-mackie-control-surface-settings-save-as-a-preset)) |
| MCU data shows up in a MIDI track recording | Track input set to Omni | Set MIDI track inputs to your keyboard instead of *All Inputs / Omni* |

`uv run apc40sonar --monitor` shows `apc:`/`mcu:` for incoming messages and
`apc>`/`mcu>` for outgoing ones, so you can tell which side of the link is failing. The
app also writes a log to `logs/apc40-sonar.log`.

> Don't open `APC40-OUT` in a MIDI monitor such as MIDI-OX while the app runs. A second
> reader can starve the app's input. Use `--monitor` instead.

### Windows 11 and Windows MIDI Services

Recent Windows 11 builds use the new Windows MIDI Services stack. loopMIDI works on it, but
cable names may come through slightly changed. Always go by what `--list-ports` shows.
If loopMIDI cables never appear even after a reboot, any other virtual MIDI loopback
driver will work too (for example a Windows MIDI Services loopback endpoint). Create two
cables and put their names in `.env`. No code changes are needed.
