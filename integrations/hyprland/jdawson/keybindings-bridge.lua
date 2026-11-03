-- Attune source bindings capabilities: disabled-v1
-- Attune source bindings capabilities: unassigned-v1
-- Trusted adapter. The mapping is data, never a Lua chunk.
local defaults_text = [=[
# Attune source bindings v1
# catalog: jdawson.hyprland
id	context	submap	flags	key	description
terminal.return	global			SUPER + Return	Open terminal (Return)
terminal.t	global			SUPER + T	Open terminal (T)
launcher.open	global			SUPER + SPACE	Open application launcher
window.close	global			SUPER + W	Close focused window
session.lock	global			SUPER + CTRL + Q	Lock session
session.power-menu	global			SUPER + CTRL + P	Open power menu
window.fullscreen	global			SUPER + F	Toggle fullscreen
window.float	global			SUPER + SHIFT + F	Toggle floating window
notes.scratch	global			SUPER + S	Open scratch notes
app.next	global			SUPER + Tab	Cycle to next application
app.previous	global			SUPER + SHIFT + Tab	Cycle to previous application
app.cancel	global			SUPER + Escape	Cancel application cycling
workspace.move-monitor	global			ALT + SHIFT + Tab	Move workspace to next monitor
clipboard.paste	global			SUPER + V	Paste clipboard
clipboard.history	global			SUPER + SHIFT + V	Open clipboard history
limbo.focus	global			SUPER + I	Focus Limbo (Super alias)
limbo.move	global			SUPER + SHIFT + I	Move window to Limbo (Super alias)
workspace.hide	global			SUPER + SHIFT + H	Hide workspace
wallpaper.pick	global			SUPER + SHIFT + B	Choose workspace wallpaper
manager.toggle	manager			ALT + G	Toggle manager mode
manager.escape	manager		auto_consuming	Escape	Cancel manager operator or exit manager mode
focus.left	global			SUPER + H	Focus left
navigate-or-manage.left	global			ALT + H	Navigate or manage left
move.left	global			ALT + SHIFT + H	Move window left
manager.direction.left	manager		auto_consuming	h	Manager direction left
focus.down	global			SUPER + J	Focus down
navigate-or-manage.down	global			ALT + J	Navigate or manage down
move.down	global			ALT + SHIFT + J	Move window down
manager.direction.down	manager		auto_consuming	j	Manager direction down
focus.up	global			SUPER + K	Focus up
navigate-or-manage.up	global			ALT + K	Navigate or manage up
move.up	global			ALT + SHIFT + K	Move window up
manager.direction.up	manager		auto_consuming	k	Manager direction up
focus.right	global			SUPER + L	Focus right
navigate-or-manage.right	global			ALT + L	Navigate or manage right
move.right	global			ALT + SHIFT + L	Move window right
manager.direction.right	manager		auto_consuming	l	Manager direction right
manager.resize	manager		auto_consuming	r	Select manager resize operator
manager.toggle-split	manager		auto_consuming	t	Toggle split in manager mode
manager.layout.full	manager		auto_consuming	1	Manager layout full
manager.layout.columns	manager		auto_consuming	2	Manager layout columns
manager.layout.two-top	manager		auto_consuming	3	Manager layout two-top
manager.layout.two-bottom	manager		auto_consuming	SHIFT + 3	Manager layout two-bottom
activity.code.focus	global			ALT + C	Focus Code activity
activity.code.move	global			ALT + SHIFT + C	Move window to Code activity
activity.action.focus	global			ALT + A	Focus Action activity
activity.action.move	global			ALT + SHIFT + A	Move window to Action activity
activity.reading.focus	global			ALT + R	Focus Reading activity
activity.reading.move	global			ALT + SHIFT + R	Move window to Reading activity
activity.amusement.focus	global			ALT + B	Focus Amusement activity
activity.amusement.move	global			ALT + SHIFT + B	Move window to Amusement activity
activity.music.focus	global			ALT + M	Focus Music activity
activity.music.move	global			ALT + SHIFT + M	Move window to Music activity
activity.exercise.focus	global			ALT + E	Focus Exercise activity
activity.exercise.move	global			ALT + SHIFT + E	Move window to Exercise activity
activity.limbo.focus	global			ALT + I	Focus Limbo activity
activity.limbo.move	global			ALT + SHIFT + I	Move window to Limbo activity
desktop.reload	global			ALT + W	Open desktop reload terminal
bindings.help	global			ALT + SHIFT + slash	Show keybindings
wisp.escape	wisp	wisp		Escape	Close Wisp
wisp.consume-space	wisp	wisp		SPACE	Consume Space in Wisp
wisp.consume-h	wisp	wisp		h	Consume former Wisp hide key
wisp.action.smiley	wisp	wisp		c	Wisp action smiley
wisp.action.scratch	wisp	wisp		s	Wisp action scratch
wisp.action.terminal	wisp	wisp		t	Wisp action terminal
wisp.action.waystone	wisp	wisp		w	Wisp action waystone
wisp.action.wyrm	wisp	wisp		r	Wisp action wyrm
wisp.open	global			ALT + SPACE	Open Wisp hints
workspace.next	global			SUPER + mouse_down	Focus next workspace
workspace.previous	global			SUPER + mouse_up	Focus previous workspace
pointer.move	global		mouse	SUPER + mouse:272	Drag window with pointer
pointer.resize	global		mouse	SUPER + mouse:273	Resize window with pointer
hardware.volume.up	global		locked,repeating	XF86AudioRaiseVolume	Raise volume
hardware.volume.down	global		locked,repeating	XF86AudioLowerVolume	Lower volume
hardware.volume.mute	global		locked	XF86AudioMute	Toggle mute
hardware.media.play	global		locked	XF86AudioPlay	Play or pause media
hardware.media.next	global		locked	XF86AudioNext	Next media track
hardware.media.previous	global		locked	XF86AudioPrev	Previous media track
hardware.brightness.up	global		locked,repeating	XF86MonBrightnessUp	Raise brightness
hardware.brightness.down	global		locked,repeating	XF86MonBrightnessDown	Lower brightness
]=]

local limit = 256 * 1024
local headers = {
  "# Attune source bindings v1",
  "# catalog: jdawson.hyprland",
  "id\tcontext\tsubmap\tflags\tkey\tdescription",
}
local known_flags = { auto_consuming = true, locked = true, repeating = true, mouse = true, disabled = true }
local modifiers = {
  SHIFT = "SHIFT", CAPS = "CAPS", CTRL = "CTRL", CONTROL = "CTRL",
  ALT = "ALT", MOD1 = "ALT", MOD2 = "MOD2", MOD3 = "MOD3",
  SUPER = "SUPER", WIN = "SUPER", LOGO = "SUPER", MOD4 = "SUPER", MOD5 = "MOD5",
}

local function shortcut(key)
  local parts = {}
  for part in (key .. "+"):gmatch("(.-)%+") do
    local trimmed = part:match("^%s*(.-)%s*$")
    assert(trimmed ~= "" and not trimmed:find("%s"), "invalid shortcut")
    parts[#parts + 1] = trimmed
  end
  local symbol = table.remove(parts):lower()
  local seen = {}
  for index, part in ipairs(parts) do
    local modifier = assert(modifiers[part:upper()], "unknown modifier")
    assert(not seen[modifier], "duplicate modifier")
    seen[modifier] = true
    parts[index] = modifier
  end
  table.sort(parts)
  return table.concat(parts, "+") .. ":" .. symbol
end

local function parse(text)
  assert(type(text) == "string" and #text <= limit, "missing or oversized catalog")
  assert(text:sub(-1) == "\n" and not text:find("[%z\1-\8\11-\31\127]"), "expected LF text without controls")
  local rows, ids, combos = {}, {}, {}
  local line_number = 0
  for line in text:gmatch("([^\n]*)\n") do
    line_number = line_number + 1
    if line_number <= 3 then
      assert(line == headers[line_number], "unexpected catalog header")
    else
      local id, context, submap, flags, key, description = line:match("^([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)$")
      assert(id and id:match("^[a-z][a-z0-9_.-]*$") and not ids[id], "invalid or duplicate ID")
      assert(context == "global" or context == "manager" or context == "wisp", "invalid context")
      assert(submap == "" or submap == "wisp", "invalid native submap")
      assert(description ~= "", "empty description")
      local options, base_flags, previous, disabled = {}, {}, "", false
      if flags ~= "" then
        for flag in (flags .. ","):gmatch("(.-),") do
          assert(known_flags[flag] and flag > previous, "unknown or unsorted flags")
          previous = flag
          if flag == "disabled" then
            disabled = true
          else
            options[flag] = true
            base_flags[#base_flags + 1] = flag
          end
        end
      end
      local assigned = key ~= ""
      assert(assigned or not disabled, "unassigned shortcut cannot be disabled")
      local combo = assigned and (submap .. "\t" .. shortcut(key))
      if assigned and not disabled then
        assert(not combos[combo], "duplicate shortcut in native submap")
        combos[combo] = true
      end
      ids[id] = true
      rows[#rows + 1] = {
        id = id, context = context, submap = submap, flags = table.concat(base_flags, ","),
        assigned = assigned, disabled = disabled,
        key = key, description = description, options = options,
      }
    end
  end
  assert(line_number == 83 and #rows == 80, "expected all 80 bindings")
  return rows
end

local defaults = parse(defaults_text)

return function(hl, path)
  local ok, selected = pcall(function()
    local file = assert(io.open(path, "rb"), "catalog unavailable")
    local read_ok, text = pcall(function() return file:read(limit + 1) end)
    file:close()
    assert(read_ok, "catalog read failed")
    local rows = parse(text)
    for index, row in ipairs(rows) do
      local original = defaults[index]
      assert(row.id == original.id and row.context == original.context
        and row.submap == original.submap and row.flags == original.flags,
        "catalog identity, order, context and flags are immutable")
    end
    return rows
  end)
  if not ok then
    print("Attune source bindings: using complete default catalog: " .. tostring(selected))
    selected = defaults
  end
  local catalog = {}
  for _, row in ipairs(selected) do catalog[row.id] = row end
  local registered, count, native_submap = {}, 0, ""
  return {
    register = function(id, action)
      local row = assert(catalog[id], "unknown source binding ID: " .. tostring(id))
      assert(not registered[id], "source binding registered twice: " .. id)
      assert(row.submap == native_submap, "source binding native submap mismatch: " .. id)
      registered[id], count = true, count + 1
      if not row.assigned or row.disabled then return end
      local options = { description = row.description }
      for flag, value in pairs(row.options) do options[flag] = value end
      return hl.bind(row.key, action, options)
    end,
    define_submap = function(name, reset, body)
      return hl.define_submap(name, reset, function()
        local previous = native_submap
        native_submap = name
        local result = body()
        native_submap = previous
        return result
      end)
    end,
    finish = function()
      assert(count == #defaults, "incomplete source binding registration")
      for _, row in ipairs(defaults) do
        assert(registered[row.id], "missing source binding ID: " .. row.id)
      end
    end,
  }
end
