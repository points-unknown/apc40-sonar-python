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

5. **Turn on meters** (for the grid level meters). Open the surface's property page
   (**Utilities > Mackie Control**) and set **Meters** to **Signal LEDs** or
   **Signal LEDs + Meters**. Cakewalk defaults this to **Off** and then sends no meter
   data at all. The setting is saved with the project, so set it in your template.
   Shortcut: with apc40sonar running, **Shift + Detail View** on the APC40 toggles it.

Cakewalk remembers these settings, so you only do this once.

### 4. Check that it works

- Move APC40 fader 1. Cakewalk track 1's volume follows.
- Mute a track with the mouse. The matching APC40 Activator LED changes.
- Press Play on the APC40. Cakewalk starts playing. With audio playing, the clip grid
  shows level meters.

## Daily startup

1. **loopMIDI** is running (automatic if Autostart is on).
2. **Start apc40sonar.** Double-click `run-apc40-sonar.cmd` in the repository root, or
   run `uv run apc40sonar`. Wait for the lightshow to finish and `running - press Ctrl+C
   to stop` to appear. Leave the window open.
3. **Open Cakewalk.**

To stop, press Ctrl+C in the apc40sonar window. A desktop shortcut to
`run-apc40-sonar.cmd` makes step 2 a single click.

Useful options: `--no-show` skips the lightshow and `--monitor` prints every MIDI
message in both directions. [`GENERAL.md`](GENERAL.md#runtime-modes) lists them all.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `error: cannot open APC40 port` | Another app holds the APC40 | Close Cakewalk (or uncheck `Akai APC40` in its MIDI Devices), MIDI-OX, Ableton, etc., then start apc40sonar again |
| `APC40-IN` / `APC40-OUT` shows `FAIL` or `MISSING` | loopMIDI not running, the cable wasn't created, or Windows renamed it | Start loopMIDI and check both cables are listed; copy the exact names from `--list-ports` into `.env`. Reboot after a fresh loopMIDI install |
| loopMIDI lists the cables but `--list-ports` does not | Driver not registered yet | Reboot with loopMIDI set to autostart, then check again |
| Lightshow runs but Cakewalk does nothing | Surface missing or ports swapped | Check that Mackie Control has Input `APC40-IN` and Output `APC40-OUT` |
| Cakewalk responds but LEDs don't follow | `APC40-OUT` not enabled as a Cakewalk output | Enable it under MIDI Devices, then re-check the surface's Output port |
| A button toggles twice per press | APC40 also set up directly in Cakewalk | Remove any APC40 device/surface in Cakewalk. Only the Mackie Control surface on the loopMIDI cables should remain |
| Grid meters stay dark with audio playing | Mackie Control **Meters** is Off (Cakewalk's default, saved per project) | Press **Shift + Detail View**, or **Utilities > Mackie Control** and set **Meters** to *Signal LEDs*. `--monitor` then shows `mcu: [208, ...]` lines |
| Shift + Detail View does nothing (log: "sent no meters") | Surface protocol set to *Universal* or *HUI* | Set the Mackie Control surface protocol back to the default, or use the property page |
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
