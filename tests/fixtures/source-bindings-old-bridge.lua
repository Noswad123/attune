-- Pre-disabled bridge. The unchanged default catalog is injected by the test.
local defaults_text = [=[
@DEFAULT_CATALOG@]=]

local limit = 256 * 1024
local headers = {
  "# Attune source bindings v1",
  "# catalog: jdawson.hyprland",
  "id\tcontext\tsubmap\tflags\tkey\tdescription",
}
local known_flags = { auto_consuming = true, locked = true, repeating = true, mouse = true }
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
      local options, previous = {}, ""
      if flags ~= "" then
        for flag in (flags .. ","):gmatch("(.-),") do
          assert(known_flags[flag] and flag > previous, "unknown or unsorted flags")
          options[flag], previous = true, flag
        end
      end
      local combo = submap .. "\t" .. shortcut(key)
      assert(not combos[combo], "duplicate shortcut in native submap")
      combos[combo], ids[id] = true, true
      rows[#rows + 1] = {
        id = id, context = context, submap = submap, flags = flags,
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
