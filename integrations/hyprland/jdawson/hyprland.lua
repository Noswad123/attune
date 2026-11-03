-- Jamal's Hyprland baseline, using Hyprland's Lua config API.
--
-- Design rule for this first Hyprland pass: keep the compositor config small
-- and boring until it has booted successfully on the Linux machine. Add richer
-- Omarchy-style behavior after `hyprctl configerrors` is clean.

------------------
---- MONITORS ----
------------------

hl.monitor({
  output = "",
  mode = "preferred",
  position = "auto",
  scale = "auto",
})

------------------
---- PROGRAMS ----
------------------

local mod = "SUPER"
local option = "ALT"
local launcher = "wofi --show drun"
local manager_mode = false
local manager_pending = nil

local function hypr_script(name)
  return "$HOME/.config/hypr/scripts/" .. name
end

local function hypr_source_script(name)
  return "$HOME/.dotfiles/stow/linux/hyprland/.config/hypr/scripts/" .. name
end

local function hypr_script_cmd(name, args)
  local script_args = args or ""
  return "sh -lc 'script=\"" .. hypr_script(name) .. "\"; [ -x \"$script\" ] || script=\"" .. hypr_source_script(name) .. "\"; \"$script\" " .. script_args .. "'"
end

local function hypr_cycle_app_cmd(action)
  return hypr_script_cmd("hypr-cycle-app", action)
end

local function sh_quote(value)
  return "'" .. tostring(value):gsub("'", "'\"'\"'") .. "'"
end

local function wisp_cmd(args)
  return "sh -lc " .. sh_quote("if command -v wisp >/dev/null 2>&1; then exec wisp " .. args .. "; elif [ -x \"$HOME/.local/bin/wisp\" ]; then exec \"$HOME/.local/bin/wisp\" " .. args .. "; else notify-send \"Wisp\" \"wisp not found\"; exit 1; fi")
end

local function hypr_terminal_cmd(title, command)
  return "sh -lc 'script=\"" .. hypr_script("hypr-terminal") .. "\"; [ -x \"$script\" ] || script=\"" .. hypr_source_script("hypr-terminal") .. "\"; exec \"$script\" --title \"$1\" -- sh -lc \"$2\"' sh " .. sh_quote(title) .. " " .. sh_quote(command)
end

local terminal = hypr_script_cmd("hypr-terminal")

local function mode_state_cmd(state)
  return "sh -lc 'printf " .. state .. " > \"${XDG_RUNTIME_DIR:-/tmp}/hypr-mode-state\"'"
end

local function write_mode_state(state)
  hl.dispatch(hl.dsp.exec_cmd(mode_state_cmd(state)))
end

local function manager_notice(message)
  hl.dispatch(hl.dsp.exec_cmd("notify-send 'Hyprland manager' " .. sh_quote(message)))
end

local function set_manager_mode(enabled)
  manager_mode = enabled
  manager_pending = nil
  if manager_mode then
    write_mode_state("manager")
    manager_notice("Arrangement mode: H/J/K/L move, R resizes, 1/2/3/Shift+3 layouts")
  else
    write_mode_state("navigation")
    manager_notice("Navigation mode")
  end
end

local function manager_only(dispatcher)
  return function()
    if manager_mode then
      return hl.dispatch(dispatcher)
    end

    return { ok = false }
  end
end

local caramel = {
  { key = "C", workspace = 1, label = "Code" },
  { key = "A", workspace = 2, label = "Action" },
  { key = "R", workspace = 3, label = "Reading" },
  -- Amusement uses B because Action already owns A.
  { key = "B", workspace = 4, label = "Amusement" },
  { key = "M", workspace = 5, label = "Music" },
  { key = "E", workspace = 6, label = "Exercise" },
  -- Limbo uses I because L is reserved for rightward window navigation.
  { key = "I", workspace = 7, label = "Limbo" },
}

-------------------
---- AUTOSTART ----
-------------------

hl.on("hyprland.start", function()
  hl.exec_cmd(mode_state_cmd("navigation"))
  hl.exec_cmd("pkill -x nm-applet 2>/dev/null || true")
  hl.exec_cmd("pkill -f '[h]ypr-workspace-wallpaper daemon' 2>/dev/null || true")
  hl.exec_cmd("hyprpaper")
  hl.exec_cmd(hypr_script_cmd("hypr-workspace-wallpaper", "apply-lock"))
  hl.exec_cmd(hypr_script_cmd("hypr-workspace-wallpaper", "daemon"))
  hl.exec_cmd(hypr_script_cmd("hypr-clipboard-watch"))
  hl.exec_cmd("sh -lc 'command -v playerctld >/dev/null 2>&1 && { pgrep -x playerctld >/dev/null 2>&1 || playerctld daemon; } || true'")
  hl.exec_cmd("waybar")
  hl.exec_cmd("mako")
  hl.exec_cmd("hyprpolkitagent")
  hl.exec_cmd("hypridle")
end)

-------------------
---- ENVIRONMENT --
-------------------

-- Keep the Xcursor theme and size in sync with GTK 3/4 settings.
hl.env("XCURSOR_THEME", "Adwaita")
hl.env("XCURSOR_SIZE", "24")

-----------------------
---- LOOK AND FEEL ----
-----------------------

hl.config({
  general = {
    gaps_in = 5,
    gaps_out = 10,
    border_size = 2,
    col = {
      active_border = { colors = { "rgba(c6a0f6ff)", "rgba(b7bdf8ff)" }, angle = 45 },
      inactive_border = "rgba(494d64cc)",
    },
    resize_on_border = true,
    layout = "dwindle",
  },

  decoration = {
    rounding = 12,
    active_opacity = 1.0,
    inactive_opacity = 0.96,
    shadow = {
      enabled = true,
      range = 18,
      render_power = 3,
      color = "rgba(181926aa)",
    },
    blur = {
      enabled = true,
      size = 4,
      passes = 2,
      vibrancy = 0.16,
    },
  },

  dwindle = {
    preserve_split = true,
  },

  misc = {
    disable_hyprland_logo = true,
    force_default_wallpaper = 0,
  },

  cursor = {
    enable_hyprcursor = false,
    hide_on_touch = false,
    no_hardware_cursors = true,
    use_cpu_buffer = true,
  },
})

---------------
---- INPUT ----
---------------

hl.config({
  input = {
    kb_layout = "us",
    follow_mouse = 1,
    sensitivity = 0,
    touchpad = {
      natural_scroll = true,
      disable_while_typing = false,
    },
  },
})

hl.gesture({
  fingers = 3,
  direction = "horizontal",
  action = "workspace",
})

---------------------
---- KEYBINDINGS ----
---------------------

-- Select one installed directory, never mix its data with another bridge.
local source_bridge
do
  local home = assert(os.getenv("HOME"), "HOME is not set")
  local directory = home .. "/.config/hypr"
  local chunk, err = loadfile(directory .. "/keybindings-bridge.lua")
  if not chunk then
    print("Attune source bindings: bridge unavailable; using original bindings: " .. tostring(err))
  else
    source_bridge = chunk()(hl, directory .. "/keybindings.tsv")
  end
end

local function source_bind(id, original_key, description, action, original_options)
  if source_bridge then return source_bridge.register(id, action) end
  local options = { description = description }
  for name, value in pairs(original_options or {}) do options[name] = value end
  return hl.bind(original_key, action, options)
end

local function source_submap(name, reset, body)
  if source_bridge then return source_bridge.define_submap(name, reset, body) end
  return hl.define_submap(name, reset, body)
end

-- Apple-style keyboard roles are preserved: Option is ALT and Command is SUPER.
-- Terminal gets two bindings so you have a fallback if a keyboard reports Return
-- differently.
source_bind("terminal.return", mod .. " + Return", "Open terminal (Return)", hl.dsp.exec_cmd(terminal))
source_bind("terminal.t", mod .. " + T", "Open terminal (T)", hl.dsp.exec_cmd(terminal))
source_bind("launcher.open", mod .. " + SPACE", "Open application launcher", hl.dsp.exec_cmd(launcher))

-- Mac-like close. No direct session-exit chord: logout is available only through
-- the power menu's confirmation prompt, with greetd as the recovery destination.
source_bind("window.close", mod .. " + W", "Close focused window", hl.dsp.window.close())
source_bind("session.lock", mod .. " + CTRL + Q", "Lock session", hl.dsp.exec_cmd(hypr_script_cmd("hypr-lock")))
source_bind("session.power-menu", mod .. " + CTRL + P", "Open power menu", hl.dsp.exec_cmd(hypr_script_cmd("hypr-power-menu")))

source_bind("window.fullscreen", mod .. " + F", "Toggle fullscreen", hl.dsp.exec_cmd("hyprctl dispatch fullscreen 0"))
source_bind("window.float", mod .. " + SHIFT + F", "Toggle floating window", hl.dsp.window.float({ action = "toggle" }))
source_bind("notes.scratch", mod .. " + S", "Open scratch notes", hl.dsp.exec_cmd(hypr_script_cmd("hypr-scratch-notes")))
source_bind("app.next", mod .. " + Tab", "Cycle to next application", hl.dsp.exec_cmd(hypr_cycle_app_cmd("next")))
source_bind("app.previous", mod .. " + SHIFT + Tab", "Cycle to previous application", hl.dsp.exec_cmd(hypr_cycle_app_cmd("prev")))
source_bind("app.cancel", mod .. " + Escape", "Cancel application cycling", hl.dsp.exec_cmd(hypr_cycle_app_cmd("cancel")))
source_bind("workspace.move-monitor", option .. " + SHIFT + Tab", "Move workspace to next monitor", hl.dsp.exec_cmd(hypr_script_cmd("hypr-workspace", "move-to-monitor next")))
source_bind("clipboard.paste", mod .. " + V", "Paste clipboard", hl.dsp.exec_cmd(hypr_script_cmd("hypr-paste")))
source_bind("clipboard.history", mod .. " + SHIFT + V", "Open clipboard history", hl.dsp.exec_cmd(hypr_script_cmd("hypr-clipboard-history")))
source_bind("limbo.focus", mod .. " + I", "Focus Limbo (Super alias)", hl.dsp.focus({ workspace = 7 }))
source_bind("limbo.move", mod .. " + SHIFT + I", "Move window to Limbo (Super alias)", hl.dsp.window.move({ workspace = 7, silent = true }))
source_bind("workspace.hide", mod .. " + SHIFT + H", "Hide workspace", hl.dsp.exec_cmd(hypr_script_cmd("hypr-hide-workspace")))
source_bind("wallpaper.pick", mod .. " + SHIFT + B", "Choose workspace wallpaper", hl.dsp.exec_cmd(
  hypr_terminal_cmd("wallpaper-picker", hypr_script_cmd("hypr-workspace-wallpaper", "pick"))
))

-- Directional navigation mirrors the Neovim/Kitsune mental model. Option is
-- the primary chord for same-workspace window navigation; Super remains as a
-- compatibility alias while the Linux workflow settles.
local directions = {
  { key = "H", local_key = "h", focus = "left", resize = { x = -60, y = 0 } },
  { key = "J", local_key = "j", focus = "down", resize = { x = 0, y = 40 } },
  { key = "K", local_key = "k", focus = "up", resize = { x = 0, y = -40 } },
  { key = "L", local_key = "l", focus = "right", resize = { x = 60, y = 0 } },
}

local function focus_window(direction)
  return hl.dispatch(hl.dsp.focus({ direction = direction.focus }))
end

local function move_window(direction)
  return hl.dispatch(hl.dsp.window.move({ direction = direction.focus }))
end

local function resize_window(direction)
  return hl.dispatch(hl.dsp.window.resize({
    x = direction.resize.x,
    y = direction.resize.y,
    relative = true,
  }))
end

local function clear_manager_pending()
  manager_pending = nil
  write_mode_state("manager")
  manager_notice("Arrangement mode")
end

local function manager_direction_action(direction)
  if not manager_mode then
    return { ok = false }
  end

  if manager_pending == "resize" then
    return resize_window(direction)
  end

  return move_window(direction)
end

local function navigate_or_manage(direction)
  return function()
    if manager_mode then
      return manager_direction_action(direction)
    else
      return focus_window(direction)
    end
  end
end

local function manager_operator(kind, message)
  return function()
    if not manager_mode then
      return { ok = false }
    end

    manager_pending = kind
    write_mode_state(kind)
    manager_notice(message)
    return { ok = true }
  end
end

source_bind("manager.toggle", option .. " + G", "Toggle manager mode", function()
  set_manager_mode(not manager_mode)
end)

source_bind("manager.escape", "Escape", "Cancel manager operator or exit manager mode", function()
  if manager_mode then
    if manager_pending then
      clear_manager_pending()
      return { ok = true }
    end

    set_manager_mode(false)
    return { ok = true }
  end

  return { ok = false }
end, { auto_consuming = true })

for _, direction in ipairs(directions) do
  source_bind("focus." .. direction.focus, mod .. " + " .. direction.key, "Focus " .. direction.focus, hl.dsp.focus({ direction = direction.focus }))
  source_bind("navigate-or-manage." .. direction.focus, option .. " + " .. direction.key, "Navigate or manage " .. direction.focus, navigate_or_manage(direction))
  source_bind("move." .. direction.focus, option .. " + SHIFT + " .. direction.key, "Move window " .. direction.focus, function()
    return move_window(direction)
  end)
  source_bind("manager.direction." .. direction.focus, direction.local_key, "Manager direction " .. direction.focus, function()
    return manager_direction_action(direction)
  end, { auto_consuming = true })
end

-- Manager-mode arrangement operators. Navigation remains separate from layout
-- mutation; this mirrors the Kitsune pane-management model.
source_bind("manager.resize", "r", "Select manager resize operator", manager_operator("resize", "Resize: press H/J/K/L; Esc returns to arrange mode"), { auto_consuming = true })
source_bind("manager.toggle-split", "t", "Toggle split in manager mode", manager_only(hl.dsp.layout("togglesplit")), { auto_consuming = true })

-- Load lazily so a missing module cannot prevent session startup or Wisp use.
-- This runs synchronously in the compositor: no racing hyprctl helper process.
local manager_layout
local function manager_preset(preset)
  return function()
    if not manager_mode then return { ok = false } end
    if manager_pending then clear_manager_pending() end
    local ok, result = pcall(function()
      if not manager_layout then
        local home = assert(os.getenv("HOME"), "HOME is not set")
        local chunk, err = loadfile(home .. "/.config/hypr/manager-layout.lua")
        if not chunk then
          chunk, err = loadfile(home .. "/.dotfiles/stow/linux/hyprland/.config/hypr/manager-layout.lua")
        end
        assert(chunk, err)
        manager_layout = chunk()
      end
      return manager_layout(hl, preset)
    end)
    if not ok then
      manager_notice("Layout failed: " .. tostring(result))
    elseif not result.ok then
      manager_notice(result.error)
    end
    -- Consume manager keys even on refusal; never type a stray digit into an app.
    return { ok = true }
  end
end

for _, binding in ipairs({
  { key = "1", preset = "full" },
  { key = "2", preset = "columns" },
  { key = "3", preset = "two-top" },
  { key = "SHIFT + 3", preset = "two-bottom" },
}) do
  source_bind("manager.layout." .. binding.preset, binding.key, "Manager layout " .. binding.preset, manager_preset(binding.preset), { auto_consuming = true })
end

-- CARAMEL activity workspaces. Option moves your attention by life activity;
-- Option+Shift sends the focused window to that activity.
for _, activity in ipairs(caramel) do
  source_bind("activity." .. activity.label:lower() .. ".focus", option .. " + " .. activity.key, "Focus " .. activity.label .. " activity", hl.dsp.focus({ workspace = activity.workspace }))
  source_bind("activity." .. activity.label:lower() .. ".move", option .. " + SHIFT + " .. activity.key, "Move window to " .. activity.label .. " activity", hl.dsp.window.move({
    workspace = activity.workspace,
    silent = true,
  }))
end

-- Desktop reload. Uses Option+W so Option+H/J/K/L can remain available for
-- same-workspace window navigation. Run inside a
-- terminal so keyd-setup can ask for sudo when needed.
source_bind("desktop.reload", option .. " + W", "Open desktop reload terminal", hl.dsp.exec_cmd(
  hypr_terminal_cmd("hypr-reload", "script=\"" .. hypr_script("hypr-reload") .. "\"; [ -x \"$script\" ] || script=\"" .. hypr_source_script("hypr-reload") .. "\"; \"$script\"; printf \"\\nPress Enter to close...\"; read _")
))
source_bind("bindings.help", option .. " + SHIFT + slash", "Show keybindings", hl.dsp.exec_cmd(
  hypr_terminal_cmd("hypr-keybindings", hypr_script_cmd("hypr-keybindings"))
))
-- Native submaps isolate these keys from manager-mode auto_consuming bindings.
-- Reset before spawning commands: a missing/failing Wisp must not trap keys.
-- Hyprland 0.56.2 opens Lua's standard libraries. Publish input order with
-- synchronous io + atomic rename, NOT an asynchronously spawned shell writer.
local wisp_runtime = os.getenv("XDG_RUNTIME_DIR")
local wisp_instance = (os.getenv("HYPRLAND_INSTANCE_SIGNATURE") or "default"):gsub("[^%w_-]", "_")
local wisp_state = wisp_runtime and (wisp_runtime .. "/wisp-hint-" .. wisp_instance .. ".session")
local wisp_epoch, wisp_serial, wisp_current = nil, 0, nil
do
  local random = io.open("/dev/urandom", "rb")
  if random then
    local bytes = random:read(16)
    random:close()
    if bytes and #bytes == 16 then
      wisp_epoch = bytes:gsub(".", function(c) return string.format("%02x", c:byte()) end)
    end
  end
end

local function publish_wisp(token)
  if not wisp_state then return false end
  local file = io.open(wisp_state .. ".tmp", "w")
  if file then
    local written = file:write((token or "") .. "\n")
    local closed = file:close()
    if written and closed and os.rename(wisp_state .. ".tmp", wisp_state) then return true end
  end
  -- Fail closed: unreadable/missing state also invalidates queued Go shows.
  os.remove(wisp_state .. ".tmp")
  os.remove(wisp_state)
  return false
end

local function wisp_close_cmd(token)
  return token and wisp_cmd("hint close --session " .. token) or "true"
end

-- Public only for the hyprctl Lua expression below. The comparison and reset
-- run in one compositor callback, so a delayed failure cannot reset a new mode.
function wisp_hint_failed(token)
  if not token or wisp_current ~= token then return { ok = true } end
  wisp_current = nil
  publish_wisp(nil)
  hl.dispatch(hl.dsp.submap("reset"))
  return hl.dispatch(hl.dsp.exec_cmd(wisp_close_cmd(token)))
end

-- A reload has a new random epoch. Invalidate and close the prior epoch too.
do
  local previous
  local file = wisp_state and io.open(wisp_state, "r")
  if file then previous = file:read("*l"); file:close() end
  publish_wisp(nil)
  if previous and previous:match("^[a-f0-9]+%-%d+$") then
    hl.dispatch(hl.dsp.exec_cmd(wisp_close_cmd(previous)))
  end
end

local function finish_wisp(command)
  return function()
    local token = wisp_current
    wisp_current = nil
    publish_wisp(nil)
    hl.dispatch(hl.dsp.submap("reset"))
    return hl.dispatch(hl.dsp.exec_cmd(
      wisp_close_cmd(token) .. (command and ("; " .. wisp_cmd(command)) or "")
    ))
  end
end

source_submap("wisp", "reset", function()
  source_bind("wisp.escape", "Escape", "Close Wisp", finish_wisp())
  -- The direct actions already cover the catalog; consume Space without search
  -- or passing a stray space into the underlying application.
  source_bind("wisp.consume-space", "SPACE", "Consume Space in Wisp", hl.dsp.no_op())
  -- Hide is not a menu action; consume its former key without affecting apps.
  source_bind("wisp.consume-h", "h", "Consume former Wisp hide key", hl.dsp.no_op())
  -- IDs/keys mirror the Linux catalog; Wisp reads hint labels from that catalog.
  for key, id in pairs({ c = "smiley", s = "scratch", t = "terminal", w = "waystone", r = "wyrm" }) do
    source_bind("wisp.action." .. id, key, "Wisp action " .. id, finish_wisp("action " .. id))
  end
end)

source_bind("wisp.open", option .. " + SPACE", "Open Wisp hints", function()
  manager_mode = false
  manager_pending = nil
  write_mode_state("navigation")
  wisp_serial = wisp_serial + 1
  local token = wisp_epoch and (wisp_epoch .. "-" .. wisp_serial)
  if not token or not publish_wisp(token) then
    wisp_current = nil
    hl.dispatch(hl.dsp.submap("reset"))
    return { ok = false }
  end
  wisp_current = token
  hl.dispatch(hl.dsp.submap("wisp"))
  local result = hl.dispatch(hl.dsp.exec_cmd(
    wisp_cmd("hint show --session " .. token .. " --state " .. sh_quote(wisp_state))
      .. " || hyprctl eval " .. sh_quote('wisp_hint_failed("' .. token .. '")')
  ))
  if not result.ok then
    wisp_hint_failed(token)
  end
  return result
end)

source_bind("workspace.next", mod .. " + mouse_down", "Focus next workspace", hl.dsp.focus({ workspace = "e+1" }))
source_bind("workspace.previous", mod .. " + mouse_up", "Focus previous workspace", hl.dsp.focus({ workspace = "e-1" }))
source_bind("pointer.move", mod .. " + mouse:272", "Drag window with pointer", hl.dsp.window.drag(), { mouse = true })
source_bind("pointer.resize", mod .. " + mouse:273", "Resize window with pointer", hl.dsp.window.resize(), { mouse = true })

-- Hardware keys. These are allowed while locked, matching the official example
-- style from Hyprland's Lua sample config.
source_bind("hardware.volume.up", "XF86AudioRaiseVolume", "Raise volume", hl.dsp.exec_cmd("pamixer -i 5"), { locked = true, repeating = true })
source_bind("hardware.volume.down", "XF86AudioLowerVolume", "Lower volume", hl.dsp.exec_cmd("pamixer -d 5"), { locked = true, repeating = true })
source_bind("hardware.volume.mute", "XF86AudioMute", "Toggle mute", hl.dsp.exec_cmd("pamixer -t"), { locked = true })
source_bind("hardware.media.play", "XF86AudioPlay", "Play or pause media", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
source_bind("hardware.media.next", "XF86AudioNext", "Next media track", hl.dsp.exec_cmd("playerctl next"), { locked = true })
source_bind("hardware.media.previous", "XF86AudioPrev", "Previous media track", hl.dsp.exec_cmd("playerctl previous"), { locked = true })
source_bind("hardware.brightness.up", "XF86MonBrightnessUp", "Raise brightness", hl.dsp.exec_cmd("brightnessctl set 10%+"), { locked = true, repeating = true })
source_bind("hardware.brightness.down", "XF86MonBrightnessDown", "Lower brightness", hl.dsp.exec_cmd("brightnessctl set 10%-"), { locked = true, repeating = true })

if source_bridge then source_bridge.finish() end
