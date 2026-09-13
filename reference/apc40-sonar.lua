-- apc40-sonar.lua
-- APC40 (original) <-> Cakewalk by BandLab integration engine (MIDIMonster v0.6).
--
-- Role:
--   * MCU encoder : translate APC40 controls into standard Mackie Control messages
--   * MCU decoder : translate Mackie Control feedback into APC40 LEDs and rings
--   * Startup lightshow (ported from baseline/apc40-startup-lightshow.lua)
--   * Mode / bank state and change-cached rendering
--
-- Requires the generated config apc40-sonar.cfg (or tools/apc40-mcu-test.cfg).
-- The channel naming contract is documented in tools/gen-apc40-sonar-config.ps1.
--
-- MCU protocol reference: docs/mcu-mapping.md
-- APC40 output reference:  docs/apc40-output-reference.md

----------------------------------------------------------------------
-- Logging
----------------------------------------------------------------------
-- Optionally appends to logs/apc40-sonar.log. The Lua backend may not expose
-- the io/os libraries, so every use is guarded and the logger degrades to a
-- no-op rather than breaking the engine.

local logfile = nil
local log_checked = false
local function log(msg)
  if not log_checked then
    log_checked = true
    if type(io) == "table" and io.open then
      local ok, f = pcall(io.open, "logs/apc40-sonar.log", "a")
      if ok then logfile = f end
    end
  end
  if logfile then
    local ts = ""
    if type(os) == "table" and os.date then ts = os.date("[%Y-%m-%d %H:%M:%S] ") end
    pcall(function() logfile:write(ts .. tostring(msg) .. "\n"); logfile:flush() end)
  end
end

-- Set true to log every MCU feedback event (very noisy; for diagnosis only).
local DEBUG = true

----------------------------------------------------------------------
-- Constants
----------------------------------------------------------------------

local TRACKS = 8
local ROWS = 5

-- APC40 note numbers
local APC_ARM, APC_SOLO, APC_MUTE, APC_SEL, APC_CLIPSTOP = 48, 49, 50, 51, 52
local APC_GRID_ROW1 = 53        -- rows 1-5 => notes 53-57
local APC_UTIL1 = 58            -- utility row => notes 58-65
local APC_MASTER = 80
local APC_STOPALL = 81
local APC_SCENE1 = 82           -- scenes 1-5 => notes 82-86
local APC_PLAY, APC_STOP, APC_REC = 91, 92, 93
local APC_UP, APC_DOWN, APC_RIGHT, APC_LEFT = 94, 95, 96, 97
local APC_SHIFT, APC_TAP, APC_NUDGEP, APC_NUDGEM = 98, 99, 100, 101

-- APC40 LED-ring controller numbers (Akai protocol rev 1, pp. 10-14)
local APC_CC_TRACK1 = 48        -- Track Control ring positions, CC 48-55
local APC_CC_TRACKSTYLE1 = 56   -- Track Control ring types, CC 56-63
local APC_CC_DEV1 = 16          -- Device Control ring positions, CC 16-23
local APC_CC_DEVSTYLE1 = 24     -- Device Control ring types, CC 24-31

-- MCU note numbers
local MCU_REC1, MCU_SOLO1, MCU_MUTE1, MCU_SEL1 = 0, 8, 16, 24
local MCU_VPUSH1 = 32
local MCU_ASSIGN_TRACK, MCU_ASSIGN_SEND, MCU_ASSIGN_PAN = 40, 41, 42
local MCU_ASSIGN_PLUGIN, MCU_ASSIGN_EQ, MCU_ASSIGN_INSTR = 43, 44, 45
local MCU_BANK_LEFT, MCU_BANK_RIGHT = 46, 47
local MCU_CHAN_LEFT, MCU_CHAN_RIGHT = 48, 49
local MCU_FLIP, MCU_GLOBAL = 50, 51
local MCU_F1 = 54
local MCU_SHIFT = 70
local MCU_SAVE, MCU_UNDO, MCU_CANCEL, MCU_ENTER = 80, 81, 82, 83
local MCU_MARKERS, MCU_NUDGE, MCU_CYCLE = 84, 85, 86
local MCU_DROP, MCU_REPLACE, MCU_CLICK, MCU_SOLO_G = 87, 88, 89, 90
local MCU_REW, MCU_FFWD, MCU_STOP, MCU_PLAY, MCU_REC = 91, 92, 93, 94, 95
local MCU_UP, MCU_DOWN, MCU_LEFT, MCU_RIGHT = 96, 97, 98, 99
local MCU_ZOOM, MCU_SCRUB = 100, 101

-- MCU V-pot CC numbers
local MCU_CC_VPOT1 = 16

-- MCU ring mode -> APC40 Device ring style (0=off,1=dot,2=volume,3=pan)
local RING_STYLE = { [0] = 1, [1] = 3, [2] = 2, [3] = 2 }

----------------------------------------------------------------------
-- State
----------------------------------------------------------------------

local state = {
  mixer = true,        -- true = Track Control knobs drive the MCU V-pots (mix)
  bank = 0,            -- track bank offset (informational)
  show_running = true, -- suppress input handling during the startup show
}

local last = {}        -- output change cache, keyed by channel name
local last_abs = {}    -- last absolute value per encoder, for delta encoding
local flashes = {}     -- pending momentary flashes

----------------------------------------------------------------------
-- Output helpers
----------------------------------------------------------------------

local function clamp01(v)
  if v < 0 then return 0 elseif v > 1 then return 1 else return v end
end

local function out(ch, v)
  v = clamp01(v)
  if last[ch] ~= v then
    output(ch, v)
    last[ch] = v
  end
end

local function force(ch, v)
  v = clamp01(v)
  output(ch, v)
  last[ch] = v
end

local function apc_note(ch, note, v7)
  out(string.format("p_n%d_%d", ch, note), v7 / 127)
end

local function apc_cc(cc, v7)
  if cc >= 48 and cc <= 55 then
    log(string.format("apc ring out cc=%d v=%d", cc, v7))
  end
  out(string.format("p_cc0_%d", cc), v7 / 127)
end

local function mcu_note(note, v7)
  out(string.format("x_note%d", note), v7 / 127)
end

-- MCU button press. Constraints discovered in practice:
--   * MIDIMonster's winmidi backend cannot emit a real Note Off; it emits Note On
--     velocity 0, and Cakewalk counts that as a SECOND press -> double toggles.
--     So we must never send 0.
--   * MIDIMonster suppresses an output value equal to the last value on a channel,
--     so a constant 127 would be dropped on alternate presses.
-- Solution: alternate the press velocity between 127 and 126. Both are valid
-- nonzero presses (exactly one toggle each) and they always differ, so every
-- press is transmitted.
local press_phase = {}
local function mcu_press(note)
  local ch = string.format("x_note%d", note)
  press_phase[note] = not press_phase[note]
  local v = press_phase[note] and 127 or 126
  force(ch, v / 127)
end

-- Knob mode selection. The original APC40 protocol defines:
--   note 87       = Pan button / LED
--   notes 88-90   = Send A / B / C buttons / LEDs
--   CC 48-55      = Track Control ring position
--   CC 56-63      = Track Control ring type (1 single, 2 volume, 3 pan)
-- These mode buttons are toggle buttons the device lights locally, so the LED
-- writes must be forced (not change-cached) or stale cache entries suppress them.
local KNOB_MODE_BUTTONS = { 87, 88, 89, 90 }
local KNOB_MODE_NOTE = { pan = 87, send_a = 88, send_b = 89, send_c = 90 }
local KNOB_MODE_ASSIGN = {
  pan = MCU_ASSIGN_PAN,
  send_a = MCU_ASSIGN_SEND,
  send_b = MCU_ASSIGN_SEND,
  send_c = MCU_ASSIGN_SEND,
}
local KNOB_MODE_STYLE = { pan = 3, send_a = 2, send_b = 2, send_c = 2 }

local function force_apc_note(ch, note, v7)
  force(string.format("p_n%d_%d", ch, note), v7 / 127)
end

local function force_apc_cc(cc, v7)
  force(string.format("p_cc0_%d", cc), v7 / 127)
end

local function set_knob_mode(mode)
  state.knob_mode = mode
  local assign = KNOB_MODE_ASSIGN[mode]
  if assign then mcu_press(assign) end

  -- Exactly one mode button lit; the others forced dark.
  local selected = KNOB_MODE_NOTE[mode]
  for _, n in ipairs(KNOB_MODE_BUTTONS) do
    force_apc_note(0, n, (n == selected) and 127 or 0)
  end

  -- Set the ring display style for all eight Track Control rings.
  local style = KNOB_MODE_STYLE[mode] or 1
  for i = 0, TRACKS - 1 do
    force_apc_cc(APC_CC_TRACKSTYLE1 + i, style)
  end

  -- Pan style centers at value 63/64 (protocol Pan table). Center the rings so
  -- the display matches a centered pan until MCU feedback arrives.
  if mode == "pan" then
    for i = 0, TRACKS - 1 do
      force_apc_cc(APC_CC_TRACK1 + i, 63)
    end
  end
end

local function mcu_pitch(ch, v)
  out(string.format("x_pitch%d", ch), v)
end

-- Relative V-pot rotation. The MCU relative encoding carries the delta in a
-- single message: 0x01-0x3F = +1..+63, 0x41-0x7F = -1..-63 (0x40 = -64).
-- Sending one message per step was slow and lossy; send the whole delta at once.
local function mcu_vpot_delta(i, delta)
  if delta == 0 then return end
  local ch = string.format("x_vpot%d", MCU_CC_VPOT1 + (i - 1))
  local v
  if delta > 0 then
    if delta > 63 then delta = 63 end
    v = delta
  else
    local d = -delta
    if d > 63 then d = 63 end
    v = 64 + d
  end
  force(ch, v / 127)
end

local function mcu_ring(i, byte)
  out(string.format("x_ring%d", 48 + (i - 1)), byte / 127)
end

----------------------------------------------------------------------
-- Momentary flash service
----------------------------------------------------------------------

local function schedule_flash(frames, onfn, offfn)
  onfn()
  table.insert(flashes, { n = frames, off = offfn })
end

local service_ticks = 0
local function service()
  service_ticks = service_ticks + 1
  -- Safety: if the startup show has not finished, stop it and draw the baseline.
  -- show_step stops itself on its next tick once state.show_running is false.
  if state.show_running and service_ticks > 240 then
    state.show_running = false
    render_baseline()
    log("show safety timeout; baseline forced")
  end

  local i = 1
  while i <= #flashes do
    local f = flashes[i]
    f.n = f.n - 1
    if f.n <= 0 then
      f.off()
      table.remove(flashes, i)
    else
      i = i + 1
    end
  end
end

----------------------------------------------------------------------
-- APC40 input handling
----------------------------------------------------------------------

local function flash_stop_all()
  apc_note(0, APC_STOP, 127)
  for t = 0, TRACKS - 1 do apc_note(t, APC_CLIPSTOP, 2) end
  schedule_flash(6, function() end, function()
    apc_note(0, APC_STOP, 0)
    for t = 0, TRACKS - 1 do apc_note(t, APC_CLIPSTOP, 0) end
  end)
end

local function apc_cc_in(ch, cc, value)
  -- Faders: CC 7 on the track channel -> MCU pitch bend (normalized pass-through)
  if cc == 7 and ch < TRACKS then
    mcu_pitch(ch, value)
    return
  end
  if ch ~= 0 then return end

  -- Track Control knobs: CC 48-55, absolute -> relative V-pot delta
  if cc >= APC_CC_TRACK1 and cc <= APC_CC_TRACK1 + 7 and state.mixer then
    local i = cc - APC_CC_TRACK1 + 1
    local abs7 = math.floor(value * 127 + 0.5)
    local prev = last_abs[i]
    if prev then
      mcu_vpot_delta(i, abs7 - prev)
    end
    last_abs[i] = abs7
    return
  end

  -- Device Control knobs: CC 16-23, drive the V-pots when in device mode
  if cc >= APC_CC_DEV1 and cc <= APC_CC_DEV1 + 7 and not state.mixer then
    local i = cc - APC_CC_DEV1 + 1
    local abs7 = math.floor(value * 127 + 0.5)
    local key = "d" .. i
    local prev = last_abs[key]
    if prev then
      mcu_vpot_delta(i, abs7 - prev)
    end
    last_abs[key] = abs7
    return
  end
end

local function apc_note_in(ch, note, value)
  local pressed = value > 0.5

  -- Per-track notes 48-57 arrive on channels 0-7.
  if ch < TRACKS and note >= APC_ARM and note <= APC_GRID_ROW1 + ROWS - 1 then
    if note >= APC_GRID_ROW1 then
      -- Grid pads: momentary green while held (grid modes come later)
      apc_note(ch, note, pressed and 1 or 0)
      return
    end
    if not pressed then return end
    if note == APC_ARM then
      mcu_press(MCU_REC1 + ch)
    elseif note == APC_SOLO then
      mcu_press(MCU_SOLO1 + ch)
    elseif note == APC_MUTE then
      mcu_press(MCU_MUTE1 + ch)
    elseif note == APC_SEL then
      mcu_press(MCU_SEL1 + ch)
    elseif note == APC_CLIPSTOP then
      mcu_press(MCU_VPUSH1 + ch)
    end
    return
  end

  -- Global controls (utility row, Master, Stop All Clips, Scenes, transport) are
  -- always on channel 0, which is shared with Track 1, so this must run after the
  -- per-track branch above.
  if ch ~= 0 then return end
  if not pressed then return end

  if note == APC_PLAY then
    mcu_press(MCU_PLAY)
  elseif note == APC_STOP then
    mcu_press(MCU_STOP)
  elseif note == APC_REC then
    mcu_press(MCU_REC)
  elseif note == APC_UP then
    mcu_press(MCU_UP)
  elseif note == APC_DOWN then
    mcu_press(MCU_DOWN)
  elseif note == APC_LEFT then
    mcu_press(MCU_LEFT)
  elseif note == APC_RIGHT then
    mcu_press(MCU_RIGHT)
  elseif note == 87 then                   -- Pan button
    set_knob_mode("pan")
  elseif note == 88 then                   -- Send A button
    set_knob_mode("send_a")
  elseif note == 89 then                   -- Send B button
    set_knob_mode("send_b")
  elseif note == 90 then                   -- Send C button
    set_knob_mode("send_c")
  elseif note == APC_UTIL1 + 7 then        -- Metronome
    mcu_press(MCU_CLICK)
  elseif note == APC_STOPALL then
    mcu_press(MCU_STOP)
    flash_stop_all()
  elseif note >= APC_SCENE1 and note <= APC_SCENE1 + 4 then
    apc_note(0, note, 127)                 -- provisional scene indication
  elseif note == APC_MASTER then
    apc_note(0, APC_MASTER, 127)
  elseif note == APC_TAP then
    apc_note(0, APC_TAP, 127)
    schedule_flash(4, function() end, function() apc_note(0, APC_TAP, 0) end)
  end
end

----------------------------------------------------------------------
-- MCU feedback handling
----------------------------------------------------------------------

local function mcu_note_in(note, value)
  local vel = math.floor(value * 127 + 0.5)
  local on = vel > 0 and 127 or 0
  if DEBUG then log(string.format("mcu note n=%d vel=%d", note, vel)) end

  if note >= MCU_REC1 and note <= MCU_REC1 + TRACKS - 1 then
    apc_note(note - MCU_REC1, APC_ARM, on)
  elseif note >= MCU_SOLO1 and note <= MCU_SOLO1 + TRACKS - 1 then
    apc_note(note - MCU_SOLO1, APC_SOLO, on)
  elseif note >= MCU_MUTE1 and note <= MCU_MUTE1 + TRACKS - 1 then
    apc_note(note - MCU_MUTE1, APC_MUTE, on)
  elseif note >= MCU_SEL1 and note <= MCU_SEL1 + TRACKS - 1 then
    apc_note(note - MCU_SEL1, APC_SEL, on)
  elseif note == MCU_PLAY then
    apc_note(0, APC_PLAY, on)
  elseif note == MCU_STOP then
    apc_note(0, APC_STOP, on)
  elseif note == MCU_REC then
    apc_note(0, APC_REC, on)
  elseif note == MCU_CLICK then
    apc_note(0, APC_UTIL1 + 7, on)         -- Metronome LED
  elseif note == MCU_CYCLE then
    apc_note(0, APC_UTIL1 + 5, on)         -- provisional: Rec Quantization LED
  end
end

local function mcu_ring_in(cc, value)
  local i = cc - 47
  if i < 1 or i > TRACKS then return end

  local byte = math.floor(value * 127 + 0.5)
  local mode = math.floor(byte / 16) % 4
  local val = byte % 16
  if val > 11 then val = 11 end
  local pos = math.floor(val / 11 * 127 + 0.5)

  if DEBUG then
    log(string.format("mcu ring cc=%d byte=%d mode=%d val=%d pos=%d", cc, byte, mode, val, pos))
  end

  if state.mixer then
    apc_cc(APC_CC_TRACK1 + (i - 1), pos)
  else
    apc_cc(APC_CC_DEV1 + (i - 1), pos)
    apc_cc(APC_CC_DEVSTYLE1 + (i - 1), RING_STYLE[mode] or 1)
  end
end

----------------------------------------------------------------------
-- Per-channel input handlers
----------------------------------------------------------------------
-- MIDIMonster calls the global Lua function whose name matches the input
-- channel. We register one function per mapped channel (this is far more
-- reliable than a single `default-handler`, for which input_channel() is not
-- guaranteed to be set). A shared guard wraps every handler so a single bad
-- event cannot stall the engine, and the show gate is applied centrally.

local function guard(fn)
  return function(value)
    -- Inputs are NEVER gated by the startup show: a control surface must always
    -- respond. The show only affects LED rendering.
    local ok, err = pcall(fn, value)
    if not ok then
      log("handler error: " .. tostring(err))
    end
  end
end

local function register_handlers()
  local ch, cc, n

  -- Faders: a_cc<ch>_7 for track channels 0-7
  for ch = 0, 7 do
    local c = ch
    _G[string.format("a_cc%d_7", c)] = guard(function(v) apc_cc_in(c, 7, v) end)
  end

  -- Device Control knobs (CC 16-23) and Track Control knobs (CC 48-55), channel 0
  for cc = 16, 23 do
    local k = cc
    _G[string.format("a_cc0_%d", k)] = guard(function(v) apc_cc_in(0, k, v) end)
  end
  for cc = 48, 55 do
    local k = cc
    _G[string.format("a_cc0_%d", k)] = guard(function(v) apc_cc_in(0, k, v) end)
  end

  -- Per-track notes 48-57 on channels 0-7
  for ch = 0, 7 do
    for n = 48, 57 do
      local c, note = ch, n
      _G[string.format("a_n%d_%d", c, note)] = guard(function(v) apc_note_in(c, note, v) end)
    end
  end

  -- Global notes 58-101 on channel 0
  for n = 58, 101 do
    local note = n
    _G[string.format("a_n0_%d", note)] = guard(function(v) apc_note_in(0, note, v) end)
  end

  -- MCU feedback notes 0-119 on channel 0
  for n = 0, 119 do
    local note = n
    _G[string.format("m_note%d", note)] = guard(function(v) mcu_note_in(note, v) end)
  end

  -- MCU fader feedback (pitch bend) is not displayable, but log it for diagnosis.
  for ch = 0, 8 do
    local c = ch
    _G[string.format("m_pitch%d", c)] = function(v)
      if DEBUG then log(string.format("mcu pitch ch=%d v=%.3f", c, v)) end
    end
  end

  -- MCU V-pot LED rings (CC 48-55)
  for cc = 48, 55 do
    local k = cc
    _G[string.format("m_ring%d", k)] = guard(function(v) mcu_ring_in(k, v) end)
  end
end

register_handlers()

----------------------------------------------------------------------
-- Startup lightshow (ported from baseline/apc40-startup-lightshow.lua)
----------------------------------------------------------------------

local frame = 0
local total_frames = 100
local frame_ms = 100

local function show_pad(track, row, state7)
  apc_note(track - 1, APC_GRID_ROW1 + (row - 1), state7)
end
local function show_clipstop(track, state7)
  apc_note(track - 1, APC_CLIPSTOP, state7)
end
local function show_strip(track, state7)
  apc_note(track - 1, APC_ARM, state7)
  apc_note(track - 1, APC_SOLO, state7)
  apc_note(track - 1, APC_MUTE, state7)
  apc_note(track - 1, APC_SEL, state7)
end
local function show_scene(row, state7)
  apc_note(0, APC_SCENE1 + (row - 1), state7)
end
local function show_top(index, state7)
  apc_note(0, APC_UTIL1 + (index - 1), state7)
end
local function show_master(state7)
  apc_note(0, APC_MASTER, state7)
end
local function show_stopall(state7)
  apc_note(0, APC_STOPALL, state7)
end
local function show_transport(note, state7)
  apc_note(0, note, state7)
end
local function show_track_ring(knob, frac)
  apc_cc(APC_CC_TRACK1 + (knob - 1), math.floor(frac * 127 + 0.5))
end
local function show_device_ring(knob, frac)
  apc_cc(APC_CC_DEV1 + (knob - 1), math.floor(frac * 127 + 0.5))
end
local function show_device_style(knob, style)
  apc_cc(APC_CC_DEVSTYLE1 + (knob - 1), style)
end

local function show_clear_grid()
  for t = 1, TRACKS do for r = 1, ROWS do show_pad(t, r, 0) end end
end
local function show_clear_clipstops()
  for t = 1, TRACKS do show_clipstop(t, 0) end
end
local function show_clear_strip()
  for t = 1, TRACKS do show_strip(t, 0) end
end
local function show_clear_scenes()
  for r = 1, ROWS do show_scene(r, 0) end
end
local function show_clear_top()
  for i = 1, 8 do show_top(i, 0) end
end
local function show_clear_transport()
  show_transport(APC_PLAY, 0)
  show_transport(APC_STOP, 0)
  show_transport(APC_REC, 0)
end
local function show_clear_rings()
  for k = 1, 8 do
    show_track_ring(k, 0)
    show_device_ring(k, 0)
    show_device_style(k, 0)
  end
end
local function show_clear_all()
  show_clear_grid()
  show_clear_clipstops()
  show_clear_strip()
  show_clear_scenes()
  show_clear_top()
  show_clear_transport()
  show_clear_rings()
  show_master(0)
  show_stopall(0)
end

local function show_diagonal(step, state7, reverse)
  show_clear_grid()
  for track = 1, TRACKS do
    local row
    if reverse then
      row = step - (TRACKS - track + 1) + 1
    else
      row = step - track + 1
    end
    if row >= 1 and row <= ROWS then
      show_pad(track, row, state7)
    end
  end
end

local function show_step()
  -- Stop as soon as the show is no longer running (completion or safety timeout).
  if not state.show_running then
    interval(show_step, 0)
    return
  end
  frame = frame + 1

  if frame == 1 then
    show_clear_all()
    for k = 1, 8 do show_device_style(k, (k % 2 == 0) and 3 or 2) end
    return
  end

  if frame >= 5 and frame <= 16 then
    show_diagonal(frame - 4, 1, false)
    show_clear_clipstops()
    show_clear_top()
    local track = ((frame - 5) % TRACKS) + 1
    show_clipstop(track, 1)
    show_top(track, 127)
    show_master((track == 1 or track == 8) and 127 or 0)
    show_stopall(0)
    return
  end

  if frame >= 17 and frame <= 28 then
    show_diagonal(frame - 16, 3, true)
    show_clear_clipstops()
    show_clear_top()
    local track = ((frame - 17) % TRACKS) + 1
    local top = TRACKS - track + 1
    show_clipstop(track, 2)
    show_top(top, 127)
    show_master(0)
    show_stopall((track == 1 or track == 8) and 2 or 0)
    return
  end

  if frame >= 29 and frame <= 38 then
    for track = 1, TRACKS do
      for row = 1, ROWS do
        local even = ((track + row + frame) % 2) == 0
        show_pad(track, row, even and 5 or 1)
      end
      show_clipstop(track, (frame % 2 == 0) and 1 or 2)
    end
    for i = 1, 8 do show_top(i, (frame % 2 == 0) and 127 or 0) end
    show_master((frame % 2 == 0) and 127 or 0)
    show_stopall((frame % 2 == 0) and 2 or 1)
    return
  end

  if frame >= 39 and frame <= 48 then
    local lead = ((frame - 39) % TRACKS) + 1
    local tail = lead - 1
    if tail < 1 then tail = TRACKS end
    show_clear_grid()
    show_clear_clipstops()
    show_clear_top()
    for row = 1, ROWS do
      show_pad(lead, row, 5)
      show_pad(tail, row, 4)
    end
    show_clipstop(lead, 1)
    show_clipstop(tail, 2)
    show_top(lead, 127)
    show_top(tail, 127)
    show_master(lead == 1 and 127 or 0)
    show_stopall(tail == TRACKS and 2 or 0)
    local sweep = ((frame - 39) % 10) / 9
    for k = 1, 8 do
      local phase = ((k - 1) % 4) / 8
      show_device_ring(k, (sweep + phase) % 1)
    end
    return
  end

  if frame >= 49 and frame <= 58 then
    local grid_state = (frame % 2 == 0) and 4 or 6
    for track = 1, TRACKS do
      for row = 1, ROWS do show_pad(track, row, grid_state) end
      show_clipstop(track, (frame % 2 == 0) and 2 or 1)
    end
    for i = 1, 8 do show_top(i, (frame % 2 == 0) and 127 or 0) end
    show_master((frame % 2 == 0) and 127 or 0)
    show_stopall((frame % 2 == 0) and 2 or 1)
    local phase = (frame - 49) / 9
    for k = 1, 8 do
      local wave = math.abs(((phase + (k - 1) / 8) % 1) * 2 - 1)
      show_device_ring(k, wave)
    end
    return
  end

  if frame >= 59 and frame <= 68 then
    show_clear_grid()
    show_clear_strip()
    show_clear_clipstops()
    show_clear_top()
    show_master(0)
    show_stopall(0)
    local track = ((frame - 59) % TRACKS) + 1
    show_strip(track, 127)
    show_clipstop(track, 1)
    show_top(track, 127)
    return
  end

  if frame >= 69 and frame <= 74 then
    show_clear_strip()
    show_clear_scenes()
    show_clear_top()
    local row = ((frame - 69) % ROWS) + 1
    show_scene(row, 127)
    for track = 1, TRACKS do show_clipstop(track, 2) end
    for i = 1, 8 do
      if ((i + frame) % 2) == 0 then show_top(i, 127) end
    end
    show_master(row == 1 and 127 or 0)
    show_stopall(2)
    return
  end

  if frame >= 75 and frame <= 83 then
    show_clear_scenes()
    show_clear_clipstops()
    show_clear_transport()
    show_clear_top()
    show_master(0)
    show_stopall(0)
    for i = 1, 8 do show_top(i, 127) end
    local phase = frame - 75
    if phase < 3 then
      show_transport(APC_PLAY, 127)
    elseif phase < 6 then
      show_transport(APC_STOP, 127)
    else
      show_transport(APC_REC, 127)
    end
    for k = 1, 8 do
      show_track_ring(k, (phase % 9) / 8)
      show_device_ring(k, ((phase + k - 1) % 9) / 8)
    end
    return
  end

  if frame >= 84 and frame <= 94 then
    show_clear_transport()
    show_clear_top()
    local visible_rows = math.min(ROWS, math.floor((frame - 84) / 2) + 1)
    for row = 1, ROWS do
      local state7 = ((row - 1) % 3) * 2 + 1
      for track = 1, TRACKS do
        show_pad(track, row, row <= visible_rows and state7 or 0)
      end
    end
    for i = 1, 8 do
      show_top(i, ((i + frame) % 2 == 0) and 127 or 0)
    end
    for k = 1, 8 do show_device_ring(k, 0.5) end
    show_master(127)
    show_stopall((frame % 2 == 0) and 2 or 1)
    return
  end

  if frame >= 95 then
    show_clear_all()
    if frame >= total_frames then
      interval(show_step, 0)
      state.show_running = false
      render_baseline()
      log("startup lightshow complete; mixer surface ready")
      print("APC40 startup lightshow complete; mixer surface ready")
    end
  end
end

----------------------------------------------------------------------
-- Baseline rendering
----------------------------------------------------------------------

function render_baseline()
  show_clear_grid()
  show_clear_clipstops()
  show_clear_top()
  show_clear_transport()
  show_stopall(0)
  -- Device Control rings default to pan style; actual values arrive from MCU feedback.
  for k = 1, 8 do show_device_style(k, 3) end
  -- Visible "engine ready" indicator: Master LED on, Scene 5 LED on.
  show_master(127)
  show_scene(5, 127)
  -- Start in a visibly and functionally explicit Pan mode.
  set_knob_mode("pan")
end

----------------------------------------------------------------------
-- Init
----------------------------------------------------------------------

log("engine loaded; starting startup lightshow")
interval(service, 50)
show_clear_all()
for k = 1, 8 do show_device_style(k, (k % 2 == 0) and 3 or 2) end
interval(show_step, frame_ms)
