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

For full-suite and GTK validation, set process `HOME`, `XDG_CONFIG_HOME`,
`XDG_STATE_HOME`, and `XDG_CACHE_HOME` to prepared temporary directories **before
Python starts**, in addition to per-test fixtures. Import-time path defaults can
otherwise retain real-user paths. Use the checkout's absolute `.venv/bin/python`
with `-m pytest` if changing HOME affects tool discovery. See
[validation isolation](docs/validation.md#validation-isolation-and-unexplained-file-observation)
for the recorded run and qualification. Do not broadly call `monkeypatch.undo()`
inside a test: use a scoped context so global HOME/XDG safety patches stay active.

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
Run `tests/test_bluetooth_page_gui.py` in the same Broadway environment for the
external Blueman handoff; all executable lookups and launches must remain mocked.
For M3.6a's separate opt-in recovery widgets, use the same Broadway environment
with `tests/test_scope_recovery_gui.py` and `tests/test_pair_editor_gui.py`. Also run
`tests/test_managed_bindings_gui.py`, `tests/test_keybindings_workflow_gui.py`
and `tests/test_source_bindings_gui.py` for bindings, plus `tests/test_input_page_gui.py`
and `tests/test_input_workflow_gui.py` for Input, plus `tests/test_cursor_page_gui.py`
and `tests/test_cursor_workflow_gui.py` for the shared Cursor view. These suites use IPC-disabled
isolation. Mutators are mocked by default; explicitly real source, managed-bindings,
Input and pair publishers are allowed only against temporary output/state/store fixtures.
Historical eight-suite Input results and pending Cursor results are distinguished in
`docs/validation.md`. Cursor backend coverage is in `tests/test_cursor_input.py`.
Focused service/wiring coverage is in
`tests/test_scoped_recovery.py`, `tests/test_layout_guard.py`, and
`tests/test_startup_layout.py`; run these alongside legacy persistence, restoration,
and recovery regressions. Coverage is not a claim that final validation passed.

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

- The user accepted the offline-validated Device/Input checkpoint ("so far so good")
  and then approved Cursor work with "continue" after Cursor was proposed next.
  This permits the narrow Cursor slice, not a claim of live Input loading or device
  verification. Cursor is implemented, pending final validation. Rules, startup and
  environment remain separately scoped later work, with no automatic expansion.
  Devices exposes 15 typed keys in 14 Keyboard/Mouse/Touchpad rows in
  admitted legacy and pair editors. The closed allowlist in `core/input.py` now has
  23 keys, including eight native Cursor keys in eight widgets:
  `no_warps`, `persistent_warps`, integer `warp_on_change_workspace` (0/1/2),
  `zoom_factor` (finite 1–10), `inactive_timeout` (finite 0–20, 0 never),
  `hide_on_key_press`, `hide_on_touch`, `hide_on_tablet`, all under `cursor:`.
  Boolean defaults are false except hide-on-touch true; warp defaults to 0, zoom
  to 1.0 and timeout to 0.0. Only these two Cursor floats use `PreciseFloatOptionRow`:
  locale-aware round-trip `Adw.EntryRow` display, explicit Apply and decimal 0.1
  +/− buttons that apply, not a one-decimal grid or GTK spin rounding/epsilon.
  Preserve unapplied numeric text outside draft/review across unrelated edits and
  Undo/Redo; whole-unit Discard and saved adoption are authoritative. Backend floats
  stay finite/bounded without step restriction. Retain public library typed-emission
  proof, refusing unrepresentable precision rather than rewriting or hand-emitting it.
  Leave existing `SpinFloatOptionRow` behavior unchanged; do not generalize this
  two-row widget into a framework. Keep the existing Devices keys:
  paired layouts/variants, raw XKB options preserving admitted unknown tags, numlock,
  repeat, mouse and touchpad controls. Both scroll factors stay at 0.1–2.0 in 0.1
  steps, not an unverified 10. No profiles/window layouts, per-device matching,
  global device-disable or keymap-file editing. Disable-while-typing is not device disable.
  Input edits/Undo/Reset/Discard are local with no preview or mutation IPC. Opening
  creates no overrides; owned values precede labeled read-only runtime/default hints.
  Layout/variant edit/Reset/Discard stay paired in one undo action.
  Preserve unapplied keyboard-options text across unrelated edits without bypassing
  Apply. Keep visible Saved/Draft/Runtime/Default origins and explicit unapplied-not-
  in-draft labeling; runtime/default values are not proof of hardware state.
- Cursor is a separate widget from `InputPage.build_cursor()`, not a second state
  owner. Devices/Cursor share one observation, draft, baseline and `_input_page`
  undo snapshots. Search/Pending/badges navigate their own views, dirty counted once.
  Edits in either invalidate the full combined review. Save Reviewed Input saves
  and adopts both views together; whole-unit Input Discard restores both. Preserve
  the other three units' drafts/baselines/undo. Uncertainty locks both views as one
  unit, not the others. Keep Devices-only canonical bytes and the input v1 record
  frozen; older Attune rejects new Cursor keys, so do not claim downgrade support.
  No theme/size/environment, `set_cursor`, GSettings or hardware/render controls;
  the inherited theme picker remains inactive. See the
  [Cursor contract](docs/architecture.md#cursor-shared-input-view).
- Input uses only dedicated `attune-input.lua`, `input.lock` and private
  `input-backups`, not shared appearance v2, a third `Scope`, registry or pair journals.
  Share narrow fixed-output safety/review/writer mechanics immediately with bindings
  through `core/owned_output.py`, Pending and window orchestration, not a generic
  plugin framework. Source TSV retains its own writer with safety-helper imports,
  protected-name updates and narrow `same_source` review matching. Keep visual v1/v2 closed.
  Require an existing safe parent, preserve Stow links and allow Linux Git output;
  the user controls commits and Attune never stages. State/backups stay outside Git.
  Complete bounded review precedes the direct non-daemon writer, global owner
  exclusion and close veto. Uncertain Input locks only Input and retains other units.
  Saving any of four units preserves the others' drafts, saved baselines and undo.
  Normal edit/review/Save/reopen/repeat must work in both admitted editor modes.
  No automatic loader/include/reload; manual `dofile` uses the actual absolute path
  only after output exists. Persistence is not loading; watched writes may reload.
  Historical Devices-only final validation passed; retain its warnings/isolation
  qualifications and counts as history, not Cursor evidence. Record final Cursor
  results only once available under [Cursor validation](docs/validation.md#cursor-implemented-final-validation-pending).
  Future live loading/checks need explicit permission. Existing source UI/last-row
  empty-field guidance is unchanged.
- For sequential independent saves, retain each page's original own-source/draft
  baseline identity and undo. Baselines carry explicit separate `protected` proofs.
  A new review may refresh only safe known sibling-output regular/absent leaf facts;
  own source plus Git context, lexical/resolved paths, symlinks/ancestors, main,
  bridge, registry and `SourceBaseline.installed_route` remain strict. Use narrow
  `same_source`/`same_protection` matching at review preparation/UI checks, never to
  silently rebase a reviewed Save. Writers recheck full exact reviewed evidence
  under lock and immediately before replacement. Post-review change invalidates
  Save. Preserve proposal/revision/draft/undo checks and adopt only the saving unit's
  verified result. The 24 real-publisher GUI cases cover all 12 ordered unit pairs
  in both legacy/pair modes, each saving all four units; keep that regression coverage.
- Current source UI correction is implemented and validated:
  one stable Keybindings list retains all 80 rows. Every pencil opens Edit Source
  Shortcut; no Delete button, Assign New or Unassigned expander. Use the actual
  installed default TSV (not Prepared): pencil -> clear Shortcut -> Update Pending
  -> Review Source -> Save Source. The row stays blank in place after Save/restart
  and its dialog opens empty. Pending says Clear shortcut (Removed), not Delete.
  Disable retains the assigned key off. Backend/state/schema and installed bridge
  capabilities are unchanged; no deployment is needed. Counts below predate this
  UI correction; its supplied final results are in
  [current validation](docs/validation.md#ui-only-correction-final-validation).
  Entering a key from blank defaults Enabled on. Live behavior remains unverified.
- Existing Keybindings still need live acceptance. The user accepted the Input
  checkpoint and approved narrow Cursor work, implemented pending final validation;
  neither establishes live loading/device behavior. Rules, startup and environment
  remain later, separately approved slices.
  Additional managed bindings have a validated checkpoint; source-aware editing is
  implemented and validated offline; the approved compatible bridge-only update is
   installed for Disable and unassignment. True Delete/unassignment is implemented and
   validated in code and isolated tests; the approved Delete-capable helper-only
   deployment completed on 2026-11-03 UTC. Runtime behavior/live acceptance
   remain pending. Profiles/layout
  pages remain out of scope. Existing-pair validation is an earlier checkpoint,
  not validation of the new bindings work. Migration and automatic foreign repair
  are deferred, nonblocking work, not feature-breadth prerequisites.
- Managed bindings use `core/bindings.py`, shared fixed-output safety in
  `core/owned_output.py`, and the dedicated fixed
  `attune-bindings.lua` format. Do not add them to visual v1/v2 payloads or pair
  journals. Retain read-only runtime/opaque rows and unknown provenance, conservative
  new/moved-combo conflicts, same-combo local edits, and unknown offline inventory.
  No main-Lua read, automatic import, override, unbind, live apply or reload.
  Capture stays GTK-only with manual fallback for reserved shortcuts.
- Source shortcuts are a separate `core/source_bindings.py` TSV workflow, not an
  extension to generated managed Lua. Write metadata only to the explicitly selected
  existing `keybindings.tsv`; preserve catalog, IDs, context, native submap, base
   flags and order. Permit key/description/assignment/enabled edits only: `assigned`
   means nonempty key; `enabled` means assigned and not metadata-only `disabled`.
   Delete/blank-field clearing stores exactly empty key without `disabled`, removing
   the old key value from the mapping, not retaining an off tombstone. Empty plus
   `disabled` is invalid. Disable separately retains the assigned key. Keep all 80
   catalog declarations, descriptions and callbacks, not necessarily 80 assigned
   bindings; no row deletion or forwarding `disabled` as a Hyprland
  option. Keep v1/all-enabled bytes unchanged. Review/commit of any disabled row
  requires the companion's first-line `-- Attune source bindings capabilities: disabled-v1`
  and captured bridge path proof; old/missing helpers must explicitly block Save,
   since the old bridge would select all defaults. Any unassigned proposal requires
   both that first line and second-line `-- Attune source bindings capabilities: unassigned-v1`.
   Apply the existing selected/actual-installed alias guard to both capabilities,
   including direct backend commits, with a clear helper-update refusal. Keep route
   and metadata binding unchanged. Keep all rows in catalog order, including blank
    shortcuts; the same pencil edits assigned, disabled and unassigned rows.
    Pending Clear shortcut is Removed, Disable/Enable Modified and assignment Added. Validate
   all three states through Undo/Redo/Discard/Revert and Save/reopen. Valid saved data
   with a compatible bridge must not resurrect defaults; absent/broken helpers or
   invalid catalog data still select whole defaults. Validate state-aware pending,
  Undo/Redo/Discard/Revert and active-only combo uniqueness, including atomic refusal
  on conflicting re-enable. The disable fix is implemented and validated through
  automated and isolated GTK checks; see the current validation record for results.
  Bind `SourceBaseline.installed_route` to the actual config-root TSV as a metadata
  `PathProof` with strict JSON validation. If selected and installed TSV share a
  resolved target or device/inode, require both companions' capability headers and
  protected proofs, even when selecting a direct Stow source. Recheck installed
  route and both proofs before state creation, under lock and immediately before
  replacement. Post-save verification may ignore only the writer's own selected
  regular-leaf identity change, including an aliased installed route; never relax
  other route/bridge facts. Unrelated offline TSVs remain independent. No main Lua
  reads/evaluation. The user-approved compatible helper-only update is installed,
   preserving TSV and main Lua; all 80 rows remain enabled. Installed `1d1023aa...`
   supports both capabilities, replacing disable-only `0fc1fa9f...`. The Delete fix is implemented
   and validated in code and isolated tests: final full pytest 4,361 passed, 383 skipped;
   six Broadway suites 380 passed, 2 skipped. Required Ruff/format and error-level
   Pyright passed; GI warnings are not claimed clear. Independent review found no
   material findings. See `docs/validation.md` for final process HOME/XDG isolation,
   the earlier non-prefixed run qualification, warnings, timings and unchanged live hashes.
   Deployment is complete, with separate in-memory Delete and Disable reviews accepted
   without persistence; app code is unchanged and no full rerun is claimed. Ready now,
    without deployment: close/reopen Attune, then installed-default `terminal.t`
    pencil / clear Shortcut / Update Pending / Review Source / Save Source. Do not apply it for the user. Configuration
   load applies it, not automatic IPC. Further live writes still
  require fresh explicit approval, not main/data replacement or automatic Super+T
  disabling. The prior disable-only helper cannot accept empty keys: do not blindly
  downgrade after Delete and resurrect defaults. Require fresh compatibility review
  and user reassignment or a safe updated-helper plan; never restore
  snapshot TSV over later edits. Keep complete reviewed Save, dedicated
  lock/private backups, fresh route/byte checks, direct non-daemon lifetime and
  source-local dirty/undo/uncertainty. Source, additional bindings and visual Save
  remain independent. Test with temporary files and process HOME/XDG isolation.
  Preserve `SourceBaseline.config_root` and immutable protected proofs for the
  actual config tree independently of selected/Stow source paths. `observe` and
  `run_observe` accept optional keyword `config_root` (XDG/home default); GUI and
  read workers pass/check explicit context. Recheck metadata-only main/generated/
  registry aliases, including post-review races, without opening authored Lua.
  Warn that saving an already-integrated/watched TSV may immediately reload it,
  even without reload IPC. Pending additional-binding rows must select that tab.
- The owner explicitly approved a **narrow exception** to the no-main-changes rule:
  an offline authored integration candidate under `integrations/hyprland/jdawson`
  may mechanically separate key declarations/labels from unchanged Lua callbacks.
  This is not authority to edit watched dotfiles, install, reload, execute authored
  main Lua in the app, or rewrite it during normal Save. Normal Attune never rewrites
  main Lua, inserts a loader, unbinds or overrides existing runtime shortcuts.
  Preserve callback bodies/definition sites and source registration order; manager
  context is Lua state, not a native submap. Whole-catalog validation selects all
  defaults on bad data; missing bridge retains original source defaults. TSV is
  never executable Lua and the trusted bridge needs no JSON dependency.
  Installation/rollback requires separate approval and the ordered plan in
  `docs/validation.md`; watcher auto-reload means no reload IPC is not no live effect.
- Keep reviewed Input, source shortcuts, additional keybindings and appearance/displays
  as four independent save units,
  including dirty baselines and undo history. Bindings commit uses its own lock,
  private hash-named backups, route/source rechecks, direct non-daemon lifetime and
  close veto. Uncertain bindings results lock only that unit. First-save guidance
  must explain manual `dofile` with the actual absolute path only after output exists;
  persistence never proves loading. See the architecture bindings contract and
  validation record for automated results and still-unverified live acceptance.
- Command validation must reject library `exec`/`execr` rewrites unless the public
  `dispatch_to_lua` result proves an `exec_cmd`/`exec_raw` quoted argument decoding
  exactly to the original command. Actual generation still uses `keyword_to_lua`.
  Test the emitted Lua body, not just metadata. Do not hand-translate rejected
  commands; offer a direct action or Raw command only when intended. Preserve exact
  dialog arguments with plaintext fallback, and keep owned-baseline Revert subject
  to owned uniqueness before mutation. Expected `ValueError`s need toast feedback.
- Normal pair Save is allowed **only** for an existing explicitly registered,
  correctly scoped canonical v2 pair with a safe initialized store and a complete
  terminal-only journal scan. Use the mature `publish_reviewed` writer, not a new
  persistence path. Registry creation/rebinding, store initialization, absent/empty
  target provisioning, and migration remain separate explicit workflows, unavailable
  through normal startup/Save. Foreign/invalid data is never an overwrite exception.
- `editor_layout.EditorEntry`, not recovery `LayoutAssessment` row actual-conflicts, selects
  startup: `legacy-clear` retains v1; `pair-ready` opens the normal pair editor;
  blocked/error results fail closed. Scan all bounded history, not just displayed
  rows; old terminal goals may disagree with a healthy current pair.
- Pair pages use local canonical models without v1 cache reads. Merge only dirty
  values/sections, preserve untouched records/siblings, supervise complete both-scope
  review off GTK, and invalidate review on edits. Publish directly on a non-daemon
  worker with close veto and owner exclusion. Only a fresh safe post-read matching
  exact reviewed goals/routes may become the new baseline before `mark_saved`,
  enabling repeated Saves. Failures retain dirty edits; pending/uncertain outcomes
  and failed post-save verification lock editing. Never mark an unverified baseline
  saved. Recovery/historical restore still invalidate old editors rather than using
  this normal-Save success path.
- Follow the [current scope](README.md#current-scope). Additional managed bindings
   and explicitly selected source keys/descriptions/enabled state are editable; authored callbacks
  and live bindings remain untouched by normal editing, and runtime origins
  are unproven. Keep workspaces, rules, autostart, environment, and other behavior outside
  the focused GUI. Inherited modules/tests do not imply supported GUI features.
- Legacy Save emits one v1 `attune.lua` only when legacy layout exclusion is clear.
  Existing canonical-pair Save uses the journaled v2 writer described above.
- Follow [ADR 0001](docs/decisions/0001-shared-local-ownership.md) for M3 development.
  Model/codec work must not activate the proposed split layout, registry, journal,
  or migration as a side effect. Existing v1 persistence remains unchanged.
- `scoped_config` and `installation` are pure data APIs used by pair editing. Structural
  registry acceptance is not filesystem approval. Keep v1 fixtures frozen; do not
  regenerate their expected bytes to make compatibility tests pass.
- `route_approval` separately inspects explicit filesystem context without mutation.
  Its transient evidence is not a write permit or activation token. Supervise
  filesystem work off GTK; writers must recheck under their own lock and
  account explicitly for any intended state-directory transitions.
- Scoped review/backup/diagnostic adapters remain read-only.
  Their hashes and canonical checks do not authorize commits or establish Lua
  semantics/runtime loading. Existing-pair Save consumes scoped review and the
  journaled backend without requiring migration or foreign preservation. Scoped
  diagnostics do not imply the legacy Health/Backups pages diagnose the pair.
- M3.6b `scoped_restore.list_sources` / `run_list` and `prepare_restore` /
  `run_prepare` only observe historical choices and canonical CURRENT -> GOAL pairs;
  use the supervised wrappers off GTK. Internal worker modes are explicitly `list`
  and `prepare`, with 1 MiB listing and 8 MiB draft transport limits.
  Keep the initialized-store requirement, both read-only pending scans, exact
  registry/roots and historical both-route binding, and current sibling isolation.
  Drafts/fingerprints are not write permits or installed/runtime/compiler proof.
  B2 browsing is explicit user-requested read-only work, never startup provisioning.
  Preserve the full 1,000-entry safety scan independently of the 32 x 4 display cap:
  truncation is not incomplete scanning, pending/corrupt evidence globally blocks,
  and incompatible historical routes are row-local blockers if globally safe.
  Old terminal recovery actual-conflict classification is not source eligibility.
  Keep the page's single async read slot through cancellation cleanup. Historical
  reviews show both scopes but never populate recovery drafts or enable the
  transaction recovery commit. B4 adds a distinct historical commit below.
  Bind completions to the requested exact DTO type, roots, and selection before
  rendering. Unexpected results must clear reviews/choices and disable commit.
  Positive historical evidence discovery must lock the running legacy editor,
  retaining dirty state; a blocked empty listing is not evidence of installation.
  B2 is implemented and validated; M3.6b remains incomplete.
  B3 `commit_restore` is implemented and validated. It is an explicit
  backend-only direct non-daemon mutator, never a timeout-killable child or CLI.
  Validate the original exact immutable draft before JSON copying; preserve delegated
  result/uncertainty flags unchanged. Recheck complete source fingerprint, snapshot,
  terminal phase, all blobs, exact review and source binding under lock before new
  evidence and through compilation, staging/checkpoints, immediately after the final
  stage read before rename, and before no-op/final success. Generated ID collisions
  must refuse, never select/reuse a PREPARED transaction. No-ops still compile and
  recheck with no journal/stages, though the store lock file may be created.
  Preserve sibling bytes/inode/mtime/mode, Stow links, and historical source evidence.
  Failures may leave a new pending transaction: use fresh explicit existing recovery,
  never replay the terminal source. Existing `commit_recovery` behavior is unchanged.
  B4's distinct GUI historical restore action/shared writer lifetime is implemented
  and validated. Only **Commit Reviewed Historical Restore** consumes its own
  `ScopedRestoreDraft`; recovery keeps its own draft/action.
  Never commit implicitly from listing/preparation. Recheck dirty/monitor-preview
  permission and owner exclusion; consume reviews/action rows before the attempt.
  Require exact read DTO/context/selection and exact `PublicationResult` types,
  boolean flags, outcomes and IDs: historical success uses a new ID, no-op none,
  recovery its reviewed ID. Invalid results/exceptions after delegation set both
  independent sticky flags; start failure before delegation adds no uncertainty.
  Define completion before fallible setup and route setup failure through clean
  pre-delegation completion. Keep essential authority cleanup independent of
  individually guarded widget operations. Retire the completion token before
  callbacks, release only the matching owner, and record sticky editor invalidation
  before fallible cache/widget notification. Notification failure must not strand
  closure or let duplicate completion release a newer owner. Never mark old baselines
  Saved. Require fresh refresh/review; show old source versus new restore ID and
  direct pending outcomes to explicit fresh recovery of the new transaction, never
  source replay or automatic recovery. Validated results are in `docs/validation.md`;
  live GUI behavior is not verified.
  B5's separate foreign-current diagnostic observer is implemented and validated,
  as detailed below. Never use unknown raw bytes as canonical priors.
  Exercise `tests/test_scoped_restore_commit.py` (including temporary real `os._exit`
  interruption), `tests/test_scoped_restore.py`, and read-only pending-scan regressions in
  `tests/test_transaction_store.py` and isolated `tests/test_scope_recovery_gui.py`
  alongside existing recovery/persistence tests. No restore writer, compilation,
  provisioning, foreign preservation, or migration is added by b2.
- B5 `scoped_foreign.observe_current` / `revalidate_current` / `run_observe` are
  backend-only diagnostics. Keep the distinct frozen `ScopedForeignObservation`:
  selected raw text/hash/proof/status has no canonical ID/counts; only the correctly
  scoped canonical sibling has them. Never return foreign `InstallationEvidence`.
  Preserve exact bytes/CRLF/final newline, strict UTF-8/control checks, 1 MiB per
  scope/10,000 selected lines, 1 MiB metadata, 8 MiB ASCII transport and depth 24.
  Validate original deep immutability, semantic hashes, UTC and exact roots/selection.
  Dispatch selected codec without expected scope first so canonical same/wrong-scope
  v2 and v1 refuse. After canonical parse failure, scan all recognized record-header
  lines independently of whole-file prefix, permitting leading BOM U+FEFF/ASCII
  space/tab for detection only. Unsupported header versions and known headers with
  embedded JSON integer versions outside v1/v2 refuse; raw text and exact-marker
  status remain unchanged. Malformed exact-marker content
  is `invalid-scoped`, other admitted text `foreign`.
  Share filesystem policy through the private collector, never a public
  `allow_foreign` flag; retain canonical inspection's both-canonical requirement and
  final dependency recheck after parsing. Transaction contents remain UNASSESSED:
  no initialized store, journal read/scan or lock for diagnostics. Pending/corrupt
  evidence is diagnostically allowed, not write authority or a protection bypass.
  Exercise `tests/test_scoped_foreign.py` with route/legacy regressions in temporary
  fixtures only. B5 adds no preservation storage, source/candidate/proposal/diff/
  commit, GUI activation, provisioning, main Lua read, compiler or IPC. B4 remains
  available. Separately design raw-preservation evidence, journal/review contracts
  and writer authority under lock, including pending-conflict checks, before a
  future foreign mutator. This work is deferred, not a canonical-only migration
  prerequisite; v1 fixtures/ownership remain unchanged.
- Private transaction evidence APIs must use explicit temporary
  state in tests. Initialization precedes route review; no startup path may create
  or repair the store. Recorded-review validation is historical/pure, not filesystem
  freshness, compilation, publication approval, or a reason to skip writer preflight.
- M3.4b publication/recovery mutators write only on explicit invocation. Keep all
  test outputs and state exclusively temporary. Existing-pair GUI Save is now an
   implemented and validated code path; do not add CLI mutation, registry
  activation, provisioning, or migration as a side effect.
  Callers must invoke mutators directly on non-daemon workers, never
  timeout-killable children. Five-second lock waits and ten-second compile checks
  do not bound total filesystem time. Honor independent sticky scope/journal
  uncertainty flags: invalidate recovery editors on scope change or uncertainty,
  never mark old baselines Saved. Normal pair Save may adopt only its freshly
  verified exact reviewed baseline as described above. M3.6a wires direct recovery
  workers, close veto, and owner-aware exclusion so legacy restoration cannot
  release a scope writer.
- Startup assessment and review preparation must stay isolated, bounded, read-only,
  and off GTK. Only `legacy-clear` permits v1 editor construction; `pair-ready`
  permits the existing canonical-pair editor. Blocked observations/errors use the
  recovery shell with manual remediation instructions, never automatic overwrite.
  Any registry or transaction
  evidence, including terminal history, excludes v1 save/restoration/preservation.
  Uninspectable metadata fails closed. Keep writer-side exclusion rechecks even
  after startup succeeds. Never infer loader choice from absence of evidence.
- Preserve untouched scopes' bytes/inode/mtime/mode and lexical symlinks. Separate
  renames are not pair-atomic; no reload IPC does not prevent watcher auto-reload.
  Recovery always needs a fresh complete CURRENT -> GOAL review. Never auto-repair,
  resume, roll back, delete evidence, or promote/reuse preexisting checkpoint scratch.
- Restore restrictive fixture permissions in `finally` and register shared fixtures
  explicitly. Targeted test success must not depend on a test module being loaded
  as a plugin in a particular collection order.
- Do not bypass review, parse/execute main Lua to discover defaults, insert
  includes, enable auto-save/startup reload, or silently register desktop files.
- Discuss larger changes with the fork owner; an upstream issue is not required.
- The user-approved Bluetooth exception is a Devices page with an explicit external
  `blueman-manager` launch. Keep it independent of Input drafts, Pending Changes,
  writer locks and editor uncertainty. No automatic launches, package installation,
  service control, discovery, pairing or native/embedded Bluetooth UI in Attune.
  Other system settings (Wi-Fi, printing, etc.) remain out of scope.

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
