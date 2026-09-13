-- Akai APC40 original: full-panel ~10-second startup lightshow, v4
-- Includes clip grid, clip stops, channel strips, Master, Stop All Clips,
-- Scene Launch, Clip/Track through Metronome, transport, and both ring banks.
-- Requires MIDIMonster v0.6 Lua backend and companion .cfg file.

local tracks = 8
local rows = 5
local frame = 0
local total_frames = 100
local frame_ms = 100
local last_grid = {}

local function set(name, value)
  output(name, value)
end

local function set_pad(track, row, state)
  local name = string.format("pad_t%d_r%d", track, row)
  if last_grid[name] ~= state then
    set(name, state / 127)
    last_grid[name] = state
  end
end

local function set_clip_stop(track, state)
  set(string.format("clipstop_t%d", track), state)
end

local function set_strip(track, state)
  set(string.format("arm_t%d", track), state)
  set(string.format("solo_t%d", track), state)
  set(string.format("mute_t%d", track), state)
  set(string.format("select_t%d", track), state)
end

local function set_scene(row, state)
  set(string.format("scene_%d", row), state)
end

local function set_top(index, state)
  set(string.format("top_%d", index), state)
end

local function set_master(state)
  set("master", state)
end

local function set_stop_all_clips(state)
  set("stop_all_clips", state)
end

local function set_transport(name, state)
  set("transport_" .. name, state)
end

local function set_track_ring(knob, value)
  set(string.format("track_ring_%d", knob), value)
end

local function set_device_ring(knob, value)
  set(string.format("device_ring_%d", knob), value)
end

local function set_device_ring_style(knob, style)
  set(string.format("device_ring_style_%d", knob), style / 127)
end

local function clear_grid()
  for track = 1, tracks do
    for row = 1, rows do
      set_pad(track, row, 0)
    end
  end
end

local function clear_clip_stops()
  for track = 1, tracks do
    set_clip_stop(track, 0)
  end
end

local function clear_strip()
  for track = 1, tracks do
    set_strip(track, 0)
  end
end

local function clear_scenes()
  for row = 1, rows do
    set_scene(row, 0)
  end
end

local function clear_top()
  for index = 1, 8 do
    set_top(index, 0)
  end
end

local function clear_transport()
  set_transport("play", 0)
  set_transport("stop", 0)
  set_transport("record", 0)
end

local function clear_rings()
  for knob = 1, 8 do
    set_track_ring(knob, 0)
    set_device_ring(knob, 0)
    set_device_ring_style(knob, 0)
  end
end

local function clear_all()
  clear_grid()
  clear_clip_stops()
  clear_strip()
  clear_scenes()
  clear_top()
  clear_transport()
  clear_rings()
  set_master(0)
  set_stop_all_clips(0)
end

local function grid_diagonal(step, state, reverse)
  clear_grid()
  for track = 1, tracks do
    local row
    if reverse then
      row = step - (tracks - track + 1) + 1
    else
      row = step - track + 1
    end
    if row >= 1 and row <= rows then
      set_pad(track, row, state)
    end
  end
end

function update()
  frame = frame + 1

  -- 0.0–0.4 s: reset and configure Device Control ring styles.
  if frame == 1 then
    clear_all()
    for knob = 1, 8 do
      set_device_ring_style(knob, (knob % 2 == 0) and 3 or 2)
    end
    return
  end

  -- 0.5–1.6 s: green diagonal grid, solid Clip Stop chase, top-row chase.
  if frame >= 5 and frame <= 16 then
    grid_diagonal(frame - 4, 1, false)
    clear_clip_stops()
    clear_top()
    local track = ((frame - 5) % tracks) + 1
    set_clip_stop(track, 1)
    set_top(track, 1)
    set_master((track == 1 or track == 8) and 1 or 0)
    set_stop_all_clips(0)
    return
  end

  -- 1.7–2.8 s: red reverse diagonal, blinking Clip Stop, reversed top-row chase.
  if frame >= 17 and frame <= 28 then
    grid_diagonal(frame - 16, 3, true)
    clear_clip_stops()
    clear_top()
    local track = ((frame - 17) % tracks) + 1
    local top = tracks - track + 1
    set_clip_stop(track, 2)
    set_top(top, 1)
    set_master(0)
    set_stop_all_clips((track == 1 or track == 8) and 2 or 0)
    return
  end

  -- 2.9–3.8 s: checkerboard and whole-panel pulse accents.
  if frame >= 29 and frame <= 38 then
    for track = 1, tracks do
      for row = 1, rows do
        local even = ((track + row + frame) % 2) == 0
        set_pad(track, row, even and 5 or 1)
      end
      set_clip_stop(track, (frame % 2 == 0) and 1 or 2)
    end
    for index = 1, 8 do
      set_top(index, (frame % 2 == 0) and 1 or 0)
    end
    set_master((frame % 2 == 0) and 1 or 0)
    set_stop_all_clips((frame % 2 == 0) and 2 or 1)
    return
  end

  -- 3.9–4.8 s: amber scanner/red tail, matching Clip Stops and top-row scan.
  if frame >= 39 and frame <= 48 then
    local lead = ((frame - 39) % tracks) + 1
    local tail = lead - 1
    if tail < 1 then tail = tracks end

    clear_grid()
    clear_clip_stops()
    clear_top()
    for row = 1, rows do
      set_pad(lead, row, 5)
      set_pad(tail, row, 4)
    end
    set_clip_stop(lead, 1)
    set_clip_stop(tail, 2)
    set_top(lead, 1)
    set_top(tail, 1)
    set_master(lead == 1 and 1 or 0)
    set_stop_all_clips(tail == tracks and 2 or 0)

    local sweep = ((frame - 39) % 10) / 9
    for knob = 1, 8 do
      local phase = ((knob - 1) % 4) / 8
      set_device_ring(knob, (sweep + phase) % 1)
    end
    return
  end

  -- 4.9–5.8 s: full grid native blink plus top row, Clip Stops, and Device wave.
  if frame >= 49 and frame <= 58 then
    local grid_state = (frame % 2 == 0) and 4 or 6
    for track = 1, tracks do
      for row = 1, rows do
        set_pad(track, row, grid_state)
      end
      set_clip_stop(track, (frame % 2 == 0) and 2 or 1)
    end
    for index = 1, 8 do
      set_top(index, (frame % 2 == 0) and 1 or 0)
    end
    set_master((frame % 2 == 0) and 1 or 0)
    set_stop_all_clips((frame % 2 == 0) and 2 or 1)

    local phase = (frame - 49) / 9
    for knob = 1, 8 do
      local wave = math.abs(((phase + (knob - 1) / 8) % 1) * 2 - 1)
      set_device_ring(knob, wave)
    end
    return
  end

  -- 5.9–6.8 s: channel-strip and Clip Stop chase, top row mirrors the chase.
  if frame >= 59 and frame <= 68 then
    clear_grid()
    clear_strip()
    clear_clip_stops()
    clear_top()
    set_master(0)
    set_stop_all_clips(0)
    local track = ((frame - 59) % tracks) + 1
    set_strip(track, 1)
    set_clip_stop(track, 1)
    set_top(track, 1)
    return
  end

  -- 6.9–7.4 s: scene chase; all Clip Stops blink; top row alternates.
  if frame >= 69 and frame <= 74 then
    clear_strip()
    clear_scenes()
    clear_top()
    local row = ((frame - 69) % rows) + 1
    set_scene(row, 1)
    for track = 1, tracks do
      set_clip_stop(track, 2)
    end
    for index = 1, 8 do
      if ((index + frame) % 2) == 0 then
        set_top(index, 1)
      end
    end
    set_master(row == 1 and 1 or 0)
    set_stop_all_clips(2)
    return
  end

  -- 7.5–8.3 s: transport chase, all eight top buttons on, both ring banks sweep.
  if frame >= 75 and frame <= 83 then
    clear_scenes()
    clear_clip_stops()
    clear_transport()
    clear_top()
    set_master(0)
    set_stop_all_clips(0)
    for index = 1, 8 do
      set_top(index, 1)
    end

    local phase = frame - 75
    if phase < 3 then
      set_transport("play", 1)
    elseif phase < 6 then
      set_transport("stop", 1)
    else
      set_transport("record", 1)
    end

    for knob = 1, 8 do
      set_track_ring(knob, (phase % 9) / 8)
      set_device_ring(knob, ((phase + knob - 1) % 9) / 8)
    end
    return
  end

  -- 8.4–9.4 s: multicolor row curtain, top row and Master/Stop All Clips finale.
  if frame >= 84 and frame <= 94 then
    clear_transport()
    clear_top()
    local visible_rows = math.min(rows, math.floor((frame - 84) / 2) + 1)
    for row = 1, rows do
      local state = ((row - 1) % 3) * 2 + 1
      for track = 1, tracks do
        set_pad(track, row, row <= visible_rows and state or 0)
      end
    end
    for index = 1, 8 do
      set_top(index, ((index + frame) % 2 == 0) and 1 or 0)
    end
    for knob = 1, 8 do
      set_device_ring(knob, 0.5)
    end
    set_master(1)
    set_stop_all_clips((frame % 2 == 0) and 2 or 1)
    return
  end

  -- 9.5–10.0 s: blackout and timer shutdown.
  if frame >= 95 then
    clear_all()
    if frame >= total_frames then
      interval(update, 0)
      print("APC40 v4 full-panel startup lightshow complete")
    end
  end
end

interval(update, frame_ms)
