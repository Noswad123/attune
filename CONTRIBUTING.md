# Contributing to Attune

Attune is a personal fork of [BlueManCZ/hyprmod](https://github.com/BlueManCZ/hyprmod)
at `b475087`. See [README.md](README.md) for supported scope and
[docs/architecture.md](docs/architecture.md) for the persistence boundary.
Keep upstream attribution and GPL-3.0-or-later licensing intact. Public commands
use `attune`; internal imports, lint targets, and tests still use `hyprmod`.

## Development setup

Use a local checkout, Python 3.12+, and uv. Native requirements include GTK4,
libadwaita, Cairo, GObject introspection development support, and Lua (`luac` or
`lua` on PATH). Debian/Ubuntu build dependency names (as used by CI):

```
libcairo2-dev libgirepository-2.0-dev libgtk-4-dev libadwaita-1-dev gir1.2-gnomedesktop-4.0
```

CI also installs `lua5.4` and uses `xvfb` for tests. On CachyOS/Arch, relevant
native packages include `gtk4`, `libadwaita`, `cairo`, `gobject-introspection`,
and `lua`. See the README for the temporary `/tmp/opencode/uv/uv` executable
when uv is not on PATH; it is not permanently installed.

For this CachyOS checkout:

```bash
cd /home/jdawson/Projects/attune
uv sync --python /usr/bin/python3
uv run attune
```

Requires Python 3.12+ and a running Hyprland instance for full manual testing.

Use uv's project environment, not system `pip`. Selecting `/usr/bin/python3`
with uv on this machine is intentional. Do not use the disabled `install.sh`,
the upstream curl installer, or launcher registration as part of normal setup.

## Before submitting a PR

Run the four checks corresponding to CI, retaining internal paths:

```bash
uv run ruff check --fix hyprmod/ tests/
uv run ruff format hyprmod/ tests/
uv run pyright hyprmod/ tests/
uv run pytest tests/ -v
```

All four should pass before a push or reporting a code task complete. Don't lean
on CI to catch formatting, lint, or type errors after the fact. CI uses
`ruff check` and `ruff format --check` without modifying files, and runs pytest
under `xvfb-run -a`; the commands above apply local lint/format fixes.
If execution is prohibited or dependencies are unavailable, report the checks as
not run and explain why. Never imply a passing suite from source inspection.

For UI changes, also run `uv run attune` against a live Hyprland and exercise the
page you touched, only with explicit permission to launch and alter compositor
state. Whole classes of bug (empty dialogs, stale state on first render,
exceptions escaping GTK callbacks) only surface at runtime. Report exactly what
you verified by hand, or state that live UI behavior was not verified.

An opt-in widget smoke suite runs with compositor IPC disabled. Start
`gtk4-broadwayd :8` in a separate terminal, then run:

```bash
ATTUNE_GUI_SMOKE=1 GDK_BACKEND=broadway BROADWAY_DISPLAY=:8 GSK_RENDERER=cairo \
  uv run pytest tests/test_gui_smoke.py -v
```

Stop the Broadway daemon when finished. These tests cover page construction,
review/save/reopen, and foreign-file recovery, not live monitor/HDR correctness.
The suite isolates HOME and XDG paths; never remove those test safety fixtures.

New pure logic under `core/` should ship with tests in `tests/`, following the existing class-based style. GTK page and widget code does not need unit tests.

Add a bullet to `CHANGELOG.md` under `## [Unreleased]` for user-visible changes.
Reference a real fork issue/PR when one exists; do not invent numbers or require
an upstream issue for personal-fork work. Preserve historical upstream entries.

Then re-read your own diff with these in mind:

- Dead fields, params, branches, imports, or attributes?
- Duplicated literals that should derive from one source?
- Thin wrappers or one-line delegators?
- Defensive `isinstance` / `try-except` / fallback for cases that can't happen?
- Comments or docstrings that just restate the code?
- Reinvented wheel where stdlib or an existing helper would do?
- Library workarounds that should be upstream changes?
- One page reaching into another's private attributes instead of a public method?

## Code style

- Python 3.12+. **No `from __future__ import ...`.**
- Ruff enforces `E`, `F`, `W`, `I` rules with a line length of 100. Always run with `--fix`.
- Pyright must pass clean. Don't use `assert` for type narrowing; restructure the code instead.
- Imports at the top of the file, not inside functions.
- Match existing patterns for pages, rows, dialogs, widgets; don't invent new ones alongside them.
- Names describe purpose, not implementation or call-stack position.
- Comments only when the *why* is non-obvious. Never restate what the code does.
- No em-dashes (`—`) in prose, commit messages, or UI strings. Use periods, commas, or colons.

## Code quality

Things to avoid:

- **Dead code**: unused fields, params, branches, imports, instance attributes that nothing reads.
- **Duplication**: derive from one canonical source instead of spelling the same list/pair twice.
- **Thin wrappers**: one-line delegators that add no semantic value. Inline them.
- **Defensive code on non-boundary values**: don't `isinstance`-check values you constructed yourself, or guard against states your own code can't produce. Only validate at real boundaries (user input, external APIs).
- **Backwards-compat shims for code being rewritten in the same PR**. Just rewrite it.
- **Workarounds in place of root-cause fixes.**
- **Reaching into another class's internals**: don't read or mutate another page's private attributes (`_owned`, `_external`, …) from outside it. Expose a public method on the owning page (e.g. `AutostartPage.has_command()`) and call that.

## UI conventions

- **Live-apply IPC from UI callbacks**: any `hypr.keyword()` / `hypr.command()` call triggered interactively by a widget (live-apply hooks, dialog Apply buttons) must be wrapped in `try_with_toast(..., catch=HyprlandError)`. If the compositor rejects the command, the exception otherwise escapes the GTK callback and leaves the UI out of sync with no feedback to the user.
- **Initialization order**: pages are built before `_register_state()` runs, so `app_state.get()` returns `None` for options during a page's `__init__` and first `build()`. Don't read live state there and assume it is populated. Hook into state notifications, or rebuild once registration is done (the window calls the page's `_rebuild_list()` after `_register_state()`).

## Commits

- One commit per coherent change. Don't bundle refactor + feature + bugfix.
- Imperative title; body explains the *why* and any trade-offs. Call out behavior changes explicitly.

## Scope

- Follow the [current scope](README.md#current-scope). Keep hand-authored
  bindings, workspaces, rules, autostart, environment, and other behavior outside
  the focused GUI. Inherited modules/tests do not imply supported GUI features.
- This milestone emits one dedicated `attune.lua` for monitors and appearance.
  Shared/machine splitting is future work, not an existing interface.
- Follow [ADR 0001](docs/decisions/0001-shared-local-ownership.md) for M3 development.
  Model/codec work must not activate the proposed split layout, registry, journal,
  or migration as a side effect. Existing v1 persistence remains the default.
- `scoped_config` and `installation` are inactive pure data APIs. Structural
  registry acceptance is not filesystem approval. Keep v1 fixtures frozen; do not
  regenerate their expected bytes to make compatibility tests pass.
- `route_approval` separately inspects explicit filesystem context without mutation.
  Its transient evidence is not a write permit or activation token. Supervise
  filesystem work off GTK; future writers must recheck under their own lock and
  account explicitly for any intended state-directory transitions.
- Do not bypass review, parse/execute main Lua to discover defaults, insert
  includes, enable auto-save/startup reload, or silently register desktop files.
- Discuss larger changes with the fork owner; an upstream issue is not required.
- System settings (Wi-Fi, Bluetooth, printing, etc.) remain out of scope.

## The `hyprland-*` library stack

The inherited parsing, IPC, schema, and state stack uses separate repositories
under [BlueManCZ](https://github.com/BlueManCZ). Attune's restricted generated-file
reader/writer lives locally in `hyprmod/core/persistence.py`:

- [`hyprland-config`](https://github.com/BlueManCZ/hyprland-config) — round-trip parser
- [`hyprland-socket`](https://github.com/BlueManCZ/hyprland-socket) — typed IPC client
- [`hyprland-schema`](https://github.com/BlueManCZ/hyprland-schema) — versioned option catalog
- [`hyprland-state`](https://github.com/BlueManCZ/hyprland-state) — unified high-level API
- [`hyprland-monitors`](https://github.com/BlueManCZ/hyprland-monitors) — scale/geometry/EDID utilities
- [`hyprland-events`](https://github.com/BlueManCZ/hyprland-events) — typed event dispatch

Keep library changes separate from fork-specific behavior. Consider an upstream
report or PR for a reproducible library bug, but do not route personal-fork scope
requests to upstream by default.

If you need a new field, behavior, or type from a library inside Attune:

1. Add it upstream first.
2. Bump the pin in `pyproject.toml`.
3. Use it natively here.

**Never** monkey-patch these libraries. That includes mutating their private state, replacing their methods or attributes, and subclassing their types to add fields they don't define. Get behavior changes upstream first.

Don't guess Hyprland's runtime behavior. Assumptions about the Lua or IPC API (what a call accepts, what a namespace contains at load time, when a value is available) must be checked against a running instance (`hyprctl`, `hyprctl eval`) or the Hyprland source, not inferred and then papered over with a workaround.

## Reporting bugs

Report fork issues to the fork owner or in this fork's tracker, if available.
Do not send Attune-specific reports automatically to the upstream HyprMod tracker.
Include:

- Hyprland version (`hyprctl version`)
- Steps to reproduce
- Relevant log output, if any
