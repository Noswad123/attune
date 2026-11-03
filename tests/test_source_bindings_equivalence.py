"""Offline declaration equivalence, not proof of live compositor behavior."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from hyprmod.core import source_bindings

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "integrations/hyprland/jdawson"
ORIGINAL = ROOT / "tests/fixtures/source-bindings-original.lua"
FROZEN_SHA256 = "f25db9b117b560a8e9ed8542be9a993be28f6990f45cdd59b9815101728c6fc4"
BINDING_IDS = tuple(
    line.split("\t", 1)[0] for line in (BUNDLE / "keybindings.tsv").read_text().splitlines()[3:]
)

# Only this harness uses the host Lua libraries. Neither configuration receives
# _G, debug, require, load, dofile, package, real io, or real os functions.
SANDBOX = r"""
local function forbidden() error("forbidden side effect", 0) end
local function hex(value)
  return (value:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end
local function lines(text)
  local result = {}
  for line in (text .. "\n"):gmatch("([^\n]*)\n") do result[#result + 1] = line end
  return result
end
local source_lines = lines(source_text)
local function snapshot(value, visiting)
  local kind = type(value)
  if kind == "function" then
    assert(not visiting[value], "unexpected cyclic callback")
    visiting[value] = true
    local info = debug.getinfo(value, "S")
    assert(info.source == "@fixture", "callback escaped fixture")
    local body = {}
    for i = info.linedefined, info.lastlinedefined do body[#body + 1] = source_lines[i] end
    body[1] = body[1]:sub(assert(body[1]:find("function", 1, true)))
    local parts = {table.concat(body, "\n")}
    local index = 1
    while true do
      local name, captured = debug.getupvalue(value, index)
      if not name then break end
      if name ~= "_ENV" then parts[#parts + 1] = name .. "=" .. snapshot(captured, visiting) end
      index = index + 1
    end
    visiting[value] = nil
    return "function{" .. table.concat(parts, ";") .. "}"
  elseif kind == "table" then
    local parts = {}
    for key, item in pairs(value) do
      parts[#parts + 1] = snapshot(key, visiting) .. "=" .. snapshot(item, visiting)
    end
    table.sort(parts)
    return "{" .. table.concat(parts, ";") .. "}"
  end
  return kind .. ":" .. tostring(value)
end
local defaults, combo_ids = {}, {}
for index, line in ipairs(lines(default_text)) do
  if index > 3 and line ~= "" then
    local id, context, submap, flags, key, description = line:match(
      "^([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)\t([^\t]*)$")
    assert(id)
    defaults[id] = {submap = submap, key = key, description = description}
    combo_ids[submap .. "\t" .. key] = id
  end
end
local current_submap, pending_id, pending_action = "", nil, nil
local records, handlers, warnings, direct = {}, {}, {}, 0
local bridge_loaded = false
local function symbolic(name)
  return function(...) return {dispatcher = name, args = table.pack(...)} end
end
local hl = {
  monitor = function() end, env = function() end,
  config = function() end, gesture = function() end,
  dispatch = forbidden, exec_cmd = forbidden,
  dsp = {
    exec_cmd = symbolic("exec_cmd"), focus = symbolic("focus"),
    layout = symbolic("layout"), submap = symbolic("submap"), no_op = symbolic("no_op"),
    window = {
      close = symbolic("window.close"), float = symbolic("window.float"),
      move = symbolic("window.move"), resize = symbolic("window.resize"),
      drag = symbolic("window.drag"),
    },
  },
}
hl.on = function(name, callback)
  assert(name == "hyprland.start" and type(callback) == "function")
  handlers[#handlers + 1] = callback -- Never invoke startup hooks.
end
hl.bind = function(key, action, options)
  if pending_id then
    assert(action == pending_action, "bridge replaced callback/dispatcher")
    direct = direct + 1
  end
  local id = pending_id or assert(combo_ids[current_submap .. "\t" .. key], "unknown fallback")
  local flags = {}
  for flag, value in pairs(options or {}) do
    if flag ~= "description" then
      assert(value == true)
      flags[#flags + 1] = flag
    end
  end
  table.sort(flags)
  records[#records + 1] = {
    id, current_submap, key, table.concat(flags, ","),
    options and options.description or "", snapshot(action, {}),
  }
end
hl.define_submap = function(name, reset, body)
  assert(name == "wisp" and reset == "reset" and current_submap == "")
  current_submap = name
  body() -- Declaration body only, not a registered action.
  current_submap = ""
end
local env = {
  assert = assert, error = error, ipairs = ipairs, pairs = pairs, next = next,
  pcall = pcall, type = type, tostring = tostring, tonumber = tonumber, select = select,
  string = {
    byte = string.byte, char = string.char, find = string.find, format = string.format,
    gmatch = string.gmatch, gsub = string.gsub, lower = string.lower, match = string.match,
    sub = string.sub, upper = string.upper,
  },
  table = {concat = table.concat, remove = table.remove, sort = table.sort},
  hl = hl,
  print = function(message) warnings[#warnings + 1] = message end,
  os = {
    getenv = function(name) if name == "HOME" then return "/virtual-home" end end,
    execute = forbidden, exit = forbidden, remove = forbidden, rename = forbidden,
  },
  io = {write = forbidden, popen = forbidden, output = forbidden},
}
env.io.open = function(path, mode)
  if path == "/dev/urandom" and mode == "rb" then return nil end
  assert(path == "/virtual-home/.config/hypr/keybindings.tsv" and mode == "rb",
    "unexpected IO: " .. tostring(path))
  if not mapping_text then return nil end
  return {
    read = function(_, size)
      assert(size == 256 * 1024 + 1, "unbounded read")
      if fault == "read-error" then error("virtual read failure") end
      return mapping_text:sub(1, size)
    end,
    close = function() return true end,
  }
end
env.loadfile = function(path)
  assert(path == "/virtual-home/.config/hypr/keybindings-bridge.lua", "unapproved code path")
  if not bridge_text then return nil, "virtual missing bridge" end
  local text = fault == "helper-syntax" and "local =" or bridge_text
  local chunk, err = load(text, "@bridge", "t", env)
  if not chunk then return nil, err end
  bridge_loaded = true
  return function()
    local factory = chunk()
    return function(...)
      local bridge = factory(...)
      local register = bridge.register
      bridge.register = function(id, action)
        pending_id, pending_action = id, action
        local result = register(id, action)
        pending_id, pending_action = nil, nil
        return result
      end
      return bridge
    end
  end
end
debug.sethook(function() error("instruction budget exceeded") end, "", 5000000)
assert(load(source_text, "@fixture", "t", env))()
debug.sethook()
assert(#records == expected_count and #handlers == 1)
if bridge_loaded then assert(direct == expected_count) else assert(direct == 0) end
for _, record in ipairs(records) do
  for index, value in ipairs(record) do record[index] = hex(value) end
  io.write(table.concat(record, "\t"), "\n")
end
io.write("STARTUP\t", hex(snapshot(handlers[1], {})), "\n")
io.write("WARNINGS\t", tostring(#warnings), "\n")
"""


def lua_text(text: str | None) -> str:
    if text is None:
        return "nil"
    # Long Lua strings normalize CRLF, hiding malformed data from the parser.
    return '"' + "".join(f"\\{byte:03d}" for byte in text.encode()) + '"'


def declarations(
    source: str,
    mapping: str | None,
    *,
    bridge: bool = True,
    fault: str | None = None,
    expected_count: int = 80,
    bridge_text: str | None = None,
):
    lua = shutil.which("lua")
    if lua is None:
        pytest.skip("lua is required for the isolated declaration test")
    script = "\n".join(
        f"local {name} = {lua_text(value)}"
        for name, value in {
            "source_text": source,
            "default_text": (BUNDLE / "keybindings.tsv").read_text(),
            "mapping_text": mapping,
            "bridge_text": (bridge_text or (BUNDLE / "keybindings-bridge.lua").read_text())
            if bridge
            else None,
            "fault": fault,
        }.items()
    )
    result = subprocess.run(
        [lua, "-E", "-"],
        input=script + f"\nlocal expected_count = {expected_count}\n" + SANDBOX,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
        env={**os.environ, "LUA_INIT": "", "LUA_INIT_5_4": "", "LUA_INIT_5_5": ""},
    )
    output = result.stdout.splitlines()
    records = [
        tuple(bytes.fromhex(field).decode() for field in line.split("\t")) for line in output[:-2]
    ]
    # Only the five Wisp pairs entries have intentionally unspecified order.
    actions = sorted(row for row in records if row[0].startswith("wisp.action."))
    canonical = []
    for row in records:
        canonical.append(actions.pop(0) if row[0].startswith("wisp.action.") else row)
    return canonical, output[-2], int(output[-1].split("\t")[1])


def edit_row(text: str, row_id: str, column: int, value: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines[3:], 3):
        fields = line.split("\t")
        if fields[0] == row_id:
            fields[column] = value
            lines[index] = "\t".join(fields)
            return "\n".join(lines) + "\n"
    raise AssertionError(row_id)


class TestSourceBindingsEquivalence:
    def test_unassign_restart_and_assign_new_declarations(self, tmp_path):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping)
        unassigned = edit_row(mapping, "terminal.t", 4, "")
        path = tmp_path / "keybindings.tsv"
        path.write_text(mapping)
        path.with_name(source_bindings.BRIDGE_BASENAME).write_bytes(
            (BUNDLE / source_bindings.BRIDGE_BASENAME).read_bytes()
        )
        baseline = source_bindings.run_observe(path, tmp_path / "state")
        proposal = source_bindings.read_text(unassigned)
        result = source_bindings.persist_reviewed(
            source_bindings.run_prepare_review(baseline, proposal), proposal
        )
        assert result.outcome == "saved", result.error
        for _ in range(2):
            reopened = source_bindings.run_observe(path, tmp_path / "state")
            assert reopened.text == unassigned and reopened.config == proposal
            after, startup_after, warnings = declarations(source, reopened.text, expected_count=79)
            assert after == [row for row in before if row[0] != "terminal.t"]
            assert any(row[0] == "terminal.return" for row in after)
            assert startup_after == startup and warnings == 0
        reassigned = edit_row(unassigned, "terminal.t", 4, "SUPER + F12")
        proposal = source_bindings.read_text(reassigned)
        result = source_bindings.persist_reviewed(
            source_bindings.run_prepare_review(
                source_bindings.run_observe(path, tmp_path / "state"), proposal
            ),
            proposal,
        )
        assert result.outcome == "saved", result.error
        after, startup_after, warnings = declarations(source, path.read_text())
        assert after == [
            row[:2] + ("SUPER + F12",) + row[3:] if row[0] == "terminal.t" else row
            for row in before
        ]
        assert startup_after == startup and warnings == 0

    def test_all_unassigned_consumes_entire_catalog_without_binds(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        source = (BUNDLE / "hyprland.lua").read_text()
        unassigned = mapping
        for row_id in BINDING_IDS:
            unassigned = edit_row(unassigned, row_id, 4, "")
        for _ in range(2):
            records, _, warnings = declarations(source, unassigned, expected_count=0)
            assert records == [] and warnings == 0
        incomplete = source.replace('source_bind("terminal.t",', 'omitted_bind("terminal.t",')
        incomplete = "local function omitted_bind(...) end\n" + incomplete
        with pytest.raises(subprocess.CalledProcessError):
            declarations(incomplete, unassigned, expected_count=0)

    def test_old_disabled_bridge_restores_defaults_for_unassigned_data(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        old_bridge = (ROOT / "tests/fixtures/source-bindings-old-disabled-bridge.lua").read_text()
        old_bridge = old_bridge.replace("@DEFAULT_CATALOG@", mapping)
        assert hashlib.sha256(old_bridge.encode()).hexdigest() == (
            "0fc1fa9f6b7351e13ef140ad62ab2a4f4832cc64af73e08c942e25e7c2fa88a8"
        )
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping, bridge_text=old_bridge)
        disabled = edit_row(mapping, "terminal.t", 3, "disabled")
        after, _, warnings = declarations(
            source, disabled, bridge_text=old_bridge, expected_count=79
        )
        assert after == [row for row in before if row[0] != "terminal.t"] and warnings == 0
        after, startup_after, warnings = declarations(
            source, edit_row(mapping, "terminal.t", 4, ""), bridge_text=old_bridge
        )
        assert after == before and startup_after == startup and warnings == 1

    @pytest.mark.parametrize("disabled_id", ["terminal.return", "terminal.t"])
    def test_disabled_key_can_be_reassigned_but_reenable_collides(self, disabled_id):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        source = (BUNDLE / "hyprland.lua").read_text()
        active_id = "terminal.t" if disabled_id == "terminal.return" else "terminal.return"
        disabled = edit_row(mapping, disabled_id, 3, "disabled")
        disabled = edit_row(disabled, disabled_id, 4, "SUPER + T")
        disabled = edit_row(disabled, active_id, 4, "win + t")
        before, startup, _ = declarations(source, mapping)
        after, startup_after, warnings = declarations(source, disabled, expected_count=79)
        expected = [
            row[:2] + ("win + t",) + row[3:] if row[0] == active_id else row
            for row in before
            if row[0] != disabled_id
        ]
        assert after == expected and startup_after == startup and warnings == 0
        for invalid in (
            edit_row(disabled, disabled_id, 3, ""),
            edit_row(disabled, disabled_id, 0, active_id),
            edit_row(disabled, disabled_id, 4, "SUPER ++ T"),
            edit_row(disabled, disabled_id, 5, ""),
        ):
            actual, _, warnings = declarations(source, invalid)
            assert actual == before and warnings == 1

    def test_disable_terminal_t_and_reenable_exact_declarations(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping)
        disabled = edit_row(mapping, "terminal.t", 3, "disabled")
        after, startup_after, warnings = declarations(source, disabled, expected_count=79)
        assert after == [row for row in before if row[0] != "terminal.t"]
        assert any(row[0] == "terminal.return" for row in after)
        assert startup_after == startup and warnings == 0
        restored, startup_restored, warnings = declarations(source, mapping)
        assert restored == before and startup_restored == startup and warnings == 0

    def test_disabled_base_flags_and_native_context_are_retained(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping)
        ids = {"manager.escape", "pointer.move", "hardware.volume.up", "wisp.action.terminal"}
        disabled = mapping
        for line in mapping.splitlines()[3:]:
            fields = line.split("\t")
            if fields[0] in ids:
                flags = sorted(filter(None, [*fields[3].split(","), "disabled"]))
                disabled = edit_row(disabled, fields[0], 3, ",".join(flags))
        after, startup_after, warnings = declarations(source, disabled, expected_count=76)
        assert after == [row for row in before if row[0] not in ids]
        assert startup_after == startup and warnings == 0
        # Bad data anywhere must discard the entire disabled selection.
        invalid = edit_row(disabled, "terminal.t", 3, "disabled,unknown")
        actual, _, warnings = declarations(source, invalid)
        assert actual == before and warnings == 1

    def test_old_bridge_restores_defaults_for_disabled_data(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        old_bridge = (ROOT / "tests/fixtures/source-bindings-old-bridge.lua").read_text()
        old_bridge = old_bridge.replace("@DEFAULT_CATALOG@", mapping)
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping, bridge_text=old_bridge)
        after, startup_after, warnings = declarations(
            source, edit_row(mapping, "terminal.t", 3, "disabled"), bridge_text=old_bridge
        )
        assert after == before and len(after) == 80
        assert startup_after == startup and warnings == 1

    def test_frozen_original_and_embedded_manifest(self):
        assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == FROZEN_SHA256
        bridge = (BUNDLE / "keybindings-bridge.lua").read_text()
        embedded = bridge.split("local defaults_text = [=[\n", 1)[1].split("]=]", 1)[0]
        assert embedded == (BUNDLE / "keybindings.tsv").read_text()

    def test_only_mechanical_registration_changes(self):
        candidate = (BUNDLE / "hyprland.lua").read_text()
        start = candidate.index("-- Select one installed directory")
        end = candidate.index("-- Apple-style keyboard roles")
        restored = candidate[:start] + candidate[end:]
        restored = re.sub(r"source_bind\([^,\n]+, ([^,\n]+), [^,\n]+, ", r"hl.bind(\1, ", restored)
        restored = restored.replace("source_submap(", "hl.define_submap(")
        restored = restored.removesuffix("\nif source_bridge then source_bridge.finish() end\n")
        assert restored == ORIGINAL.read_text()

    def test_default_registration_equivalence(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        before, startup_before, _ = declarations(ORIGINAL.read_text(), mapping, bridge=False)
        after, startup_after, warnings = declarations(
            (BUNDLE / "hyprland.lua").read_text(), mapping
        )
        assert len(before) == len(after) == len({row[0] for row in after}) == 80
        assert [row[:4] + row[5:] for row in before] == [row[:4] + row[5:] for row in after]
        assert startup_before == startup_after
        assert warnings == 0
        manifest = {
            fields[0]: fields for fields in (r.split("\t") for r in mapping.splitlines()[3:])
        }
        for row in after:
            fields = manifest[row[0]]
            assert row[1:5] == (fields[2], fields[4], fields[3], fields[5])
            if fields[1] == "manager":
                assert row[1] == ""  # Manager is not a native submap.

    @pytest.mark.parametrize("row_id", BINDING_IDS)
    def test_single_edit_changes_only_key_and_description(self, row_id):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        edited = edit_row(mapping, row_id, 4, "CTRL + SUPER + Return")
        edited = edit_row(edited, row_id, 5, "My binding")
        source = (BUNDLE / "hyprland.lua").read_text()
        before, startup, _ = declarations(source, mapping)
        after, startup_after, warnings = declarations(source, edited)
        assert startup == startup_after and warnings == 0
        for old, new in zip(before, after, strict=True):
            if old[0] == row_id:
                assert new == old[:2] + ("CTRL + SUPER + Return", old[3], "My binding", old[5])
            else:
                assert new == old

    @pytest.mark.parametrize(
        "invalid",
        [
            "missing",
            "partial",
            "unknown",
            "reordered",
            "context",
            "submap",
            "flags",
            "duplicate-id",
            "collision",
            "modifier-order-collision",
            "manager-collision",
            "crlf",
            "control",
            "extra-field",
            "header",
            "catalog",
            "no-final-lf",
            "oversized",
            "bad-key",
            "blank-key",
            "unassigned-disabled",
            "empty-description",
            "executable-data",
        ],
    )
    def test_invalid_mapping_uses_entire_defaults(self, invalid):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        changed = edit_row(mapping, "terminal.return", 4, "SUPER + F12")
        variants = {
            "missing": None,
            "partial": changed.rsplit("\n", 2)[0] + "\n",
            "unknown": edit_row(changed, "terminal.t", 0, "unknown.id"),
            "reordered": "\n".join(
                changed.splitlines()[:3]
                + changed.splitlines()[4:5]
                + changed.splitlines()[3:4]
                + changed.splitlines()[5:]
            )
            + "\n",
            "context": edit_row(changed, "manager.escape", 1, "global"),
            "submap": edit_row(changed, "manager.escape", 2, "wisp"),
            "flags": edit_row(changed, "manager.escape", 3, "locked"),
            "duplicate-id": edit_row(changed, "terminal.t", 0, "terminal.return"),
            "collision": edit_row(changed, "terminal.t", 4, "super + f12"),
            "modifier-order-collision": edit_row(changed, "terminal.t", 4, "CTRL + SUPER + Q"),
            "manager-collision": edit_row(changed, "manager.resize", 4, "Escape"),
            "crlf": changed.replace("\n", "\r\n"),
            "control": edit_row(changed, "terminal.t", 5, "label\x00"),
            "extra-field": edit_row(changed, "terminal.t", 5, "label\textra"),
            "header": changed.replace("bindings v1", "bindings v2"),
            "catalog": changed.replace("jdawson.hyprland", "other.hyprland"),
            "no-final-lf": changed.rstrip("\n"),
            "oversized": changed + "x" * (256 * 1024),
            "bad-key": edit_row(changed, "terminal.t", 4, "SUPER ++ T"),
            "blank-key": edit_row(changed, "terminal.t", 4, "   "),
            "unassigned-disabled": edit_row(
                edit_row(changed, "terminal.t", 4, ""), "terminal.t", 3, "disabled"
            ),
            "empty-description": edit_row(changed, "terminal.t", 5, ""),
            "executable-data": 'os.execute("false")\n',
        }
        source = (BUNDLE / "hyprland.lua").read_text()
        expected, startup, _ = declarations(source, mapping)
        actual, startup_after, warnings = declarations(source, variants[invalid])
        assert actual == expected and startup_after == startup
        assert warnings == 1

    def test_missing_bridge_preserves_original_registrations(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        expected, startup, _ = declarations(ORIGINAL.read_text(), mapping, bridge=False)
        actual, startup_after, warnings = declarations(
            (BUNDLE / "hyprland.lua").read_text(), None, bridge=False
        )
        assert [row[:4] + row[5:] for row in actual] == [row[:4] + row[5:] for row in expected]
        assert startup_after == startup and warnings == 1

    @pytest.mark.parametrize("fault", ["read-error", "helper-syntax"])
    def test_virtual_failures_preserve_all_default_registrations(self, fault):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        changed = edit_row(mapping, "terminal.return", 4, "SUPER + F12")
        source = (BUNDLE / "hyprland.lua").read_text()
        expected, startup, _ = declarations(source, mapping)
        actual, startup_after, warnings = declarations(source, changed, fault=fault)
        assert actual == expected and startup_after == startup
        assert warnings == 1

    def test_same_key_in_different_native_submaps_is_valid(self):
        mapping = (BUNDLE / "keybindings.tsv").read_text()
        _, _, warnings = declarations((BUNDLE / "hyprland.lua").read_text(), mapping)
        assert warnings == 0  # Escape, h, r and t legitimately repeat across submaps.

    @pytest.mark.parametrize("violation", ["unknown", "duplicate", "missing", "native-context"])
    def test_registration_consistency_assertions(self, violation):
        source = (BUNDLE / "hyprland.lua").read_text()
        extra = {
            "unknown": 'source_bind("unknown.id", "F12", "Unknown", hl.dsp.no_op())\n',
            "duplicate": 'source_bind("terminal.t", "F12", "Duplicate", hl.dsp.no_op())\n',
            "native-context": 'source_bind("wisp.escape", "Escape", "Wrong", hl.dsp.no_op())\n',
        }
        if violation == "missing":
            source = "\n".join(
                line
                for line in source.split("\n")
                if not line.startswith('source_bind("terminal.t",')
            )
        else:
            source = source.replace(
                "if source_bridge then source_bridge.finish() end",
                extra[violation] + "if source_bridge then source_bridge.finish() end",
            )
        with pytest.raises(subprocess.CalledProcessError):
            declarations(source, (BUNDLE / "keybindings.tsv").read_text())

    def test_sandbox_refuses_side_effects(self):
        source = (BUNDLE / "hyprland.lua").read_text()
        for forbidden in (
            'os.execute("true")',
            'io.open("/real-user", "r")',
            "hl.dispatch(hl.dsp.no_op())",
            'hl.exec_cmd("true")',
            'loadfile("/real-code")',
            'require("os")',
        ):
            with pytest.raises(subprocess.CalledProcessError):
                declarations(forbidden + "\n" + source, None)

    def test_lua_syntax_only(self):
        luac = shutil.which("luac")
        if luac is None:
            pytest.skip("luac is required for parse-only validation")
        for path in (ORIGINAL, BUNDLE / "hyprland.lua", BUNDLE / "keybindings-bridge.lua"):
            subprocess.run([luac, "-p", str(path)], check=True, capture_output=True, timeout=10)
