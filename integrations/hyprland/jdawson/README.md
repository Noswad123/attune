# Offline Source Bindings Bundle

This directory remains a reference bundle outside watched dotfiles/config, not a
directory directly loaded by the live configuration. **User-approved deployment of
reviewed copies completed on 2026-11-02** into the actual Stow source, preserving
the config-root symlink. No automatic installer was added.
Existing scripts, callbacks, startup behavior, manager state and Wisp state are
not moved into editable data.

## Overview

**Current UI correction:** implemented and validated. One stable
Keybindings list keeps all 80 rows; every pencil opens Edit Source Shortcut. There
is no Delete button, Assign New or Unassigned expander. Use the actual installed
default `/home/jdawson/.config/hypr/keybindings.tsv`, not this Prepared copy:
pencil -> clear Shortcut -> Update Pending -> Review Source -> Save Source.
The same row stays blank after Save/restart and its dialog opens empty. Pending
says Clear shortcut; Disable retains the assigned key off. Backend/state/schema
and installed bridge capabilities are unchanged; no deployment is needed.
Entering a key from blank defaults Enabled on. Final full pytest **4,361 passed,
383 skipped**; six isolated Broadway suites **380 passed, 2 skipped**. See
[current validation](../../../docs/validation.md#ui-only-correction-final-validation)
for supplied final results and limits; live behavior remains unverified. Validation
counts below predate this correction. Historical records are not instructions to redeploy.

True Delete/unassignment is **implemented and validated in code and isolated tests**.
The user-approved Delete-capable bridge-only deployment completed on 2026-11-03 UTC.
Installed `1d1023aa...` supports both `disabled-v1` and `unassigned-v1`, replacing
disable-only `0fc1fa9f...` without changing main Lua or mappings. Separate in-memory
Delete and Disable reviews passed without persistence. The user's installed-default
pencil / clear Shortcut / Update Pending / Review Source / Save Source workflow
needs no deployment. No live update or deletion was performed by this documentation pass.

The original key/description editor has a validated checkpoint. The checkout's earlier
reversible disable fix is **implemented and validated in code** through automated
and isolated GTK checks. The user-approved compatible bridge-only update completed
on 2026-11-03 UTC, preserving main Lua and TSV. The on-disk capability guard passes. Live
TSV remains all 80 enabled, SHA-256
`7a6d5d6145ccb5c1a39be965541306b46da6b821b0a0f44d2fa58796f79db3d7`.
No Super+T disable has been performed. Close/reopen Attune
-> Keybindings -> Existing shortcuts uses the installed default TSV; installed-path
observation succeeded with 80 rows. **Open Prepared Source Mappings** opens this
directory's TSV now for key/description/enabled drafting, full review and independent Save.
It neither installs this bundle nor changes the active config. Additional bindings
and visual changes save separately. If another selected TSV is already integrated
or watched, saving it may trigger an **immediate reload**, even without reload IPC.

## Files and Contract

- `hyprland.lua`: full candidate main config, with mechanical binding-call changes.
- `keybindings-bridge.lua`: trusted code, including a frozen 80-row default catalog.
- `keybindings.tsv`: editable key/description/enabled metadata, initially identical to that catalog.

The data file is LF-only text, including a final LF, bounded to 256 KiB. Its exact
first three lines are:

```text
# Attune source bindings v1
# catalog: jdawson.hyprland
id	context	submap	flags	key	description
```

The `\t` above denotes one literal tab. Each of the following **80 rows** has
exactly six fields in that order. There is no escaping, quoting, continuation,
comment extension, or Lua evaluation. Tabs/newlines cannot occur within fields;
NUL, CR, other ASCII controls and DEL are rejected. Descriptions must be nonempty.

Only `key`, `description` and assignment/enabled state may change. `assigned` means
`key != ""`; `enabled` means assigned and not metadata-only `disabled`. The v1 marker
and all-enabled bytes stay unchanged. IDs, row order, context, native submap
and base flags must match the embedded defaults exactly. All 80 records stay present,
retaining descriptions and authored callbacks, not row deletion. These are 80
declarations, not necessarily 80 assigned bindings. Delete/blank-field clearing
stores exactly empty key without `disabled`, removing the old key value, not an
off tombstone. Empty plus `disabled` is invalid. Disable separately retains the key.
IDs describe individual
registrations, including aliases: `terminal.return` and `terminal.t` are distinct,
as are `limbo.focus` and `activity.limbo.focus`. Direction IDs use `direction.focus`;
activity IDs use the activity label; Wisp IDs use the **action ID**, never its
editable key. The full ID/default/description inventory is `keybindings.tsv`.

`context` is a descriptive grouping: `global`, `manager` or `wisp`. **Manager is
Lua state, not a native submap.** Its native `submap` field is empty, just like
other global bindings. Wisp's native submap is `wisp`. `wisp.open` is global.
`flags` is a lexicographically sorted comma-separated list of original true
options: `auto_consuming`, `locked`, `mouse`, `repeating`; empty means none.
The optional sorted `disabled` token is metadata only, never a Hyprland option.

Keys retain the original `hl.bind` spelling, case, modifier order and spaces in
the initial catalog. The bridge forwards an accepted edited key verbatim. It
requires one key token with optional `+`-separated modifiers, rejects empty tokens
and repeated modifiers, and compares shortcuts case-insensitively with whitespace
trimmed, modifiers sorted, and common modifier aliases folded (`CONTROL`/`CTRL`,
`MOD1`/`ALT`, `MOD4`/`SUPER`/`WIN`/`LOGO`). This is conservative local collision
checking, not a claim to validate all compositor keysym aliases or hardware maps.
No collision between enabled rows in one native submap is accepted, even between
descriptive contexts. A disabled combo is free for another enabled source row;
conflicting re-enable refuses atomically before draft mutation.
The initial catalog has **no normalized collisions within a native submap**;
Escape/h/r/t occurring both globally and in Wisp are legitimate and tested.

Data order is immutable catalog presentation, **not activation order**. Original
source positions control registration order. In particular the Wisp action loop
still uses `pairs`, whose order is unspecified; it is not converted to `ipairs`.

## API / Interfaces: Bridge

The trusted module returns a factory:

```lua
local bridge = trusted_chunk()(hl, selected_directory .. "/keybindings.tsv")
bridge.register(id, original_action)
bridge.define_submap(name, reset, declaration_body)
bridge.finish()
```

The factory reads and validates the **entire** mapping before the first binding.
Missing, unreadable, oversized, partial, unknown, duplicate, reordered, malformed,
metadata-edited or colliding data selects the **entire embedded default catalog**.
It prints one warning using Lua's core `print`; it never writes or repairs data
and does not assume a `hl.log` API. Data is read only through bounded `io.open`;
there is no Lua/JSON parser dependency and no `load`/`dofile` on data.

`register` passes the action callback/dispatcher object directly to `hl.bind`
without wrapping, invoking or replacing it, adds `description`, and supplies the
frozen original flags. It verifies native declaration context and single use.
For disabled or unassigned rows it still consumes/checks the ID and native context but skips
`hl.bind` entirely. It never forwards `disabled` in options.
`define_submap` delegates the same name/reset and runs the same declaration body
while tracking its native context. `finish` asserts complete, unique registration
of all 80 declaration IDs with no extras, not 80 emitted bindings. These are trusted-source consistency assertions,
not recovery for a broken candidate/bridge implementation.

The candidate companion begins with these exact ordered capability lines:

```lua
-- Attune source bindings capabilities: disabled-v1
-- Attune source bindings capabilities: unassigned-v1
```

Old all-enabled TSV works with old/new bridges. An old bridge cannot honor
`disabled` and would reject the whole catalog, selecting **all 80 defaults**.
App review and commit of any disabled row therefore require this first-line header
and the companion's captured path proof. Old/missing helpers explicitly block Save
with a helper-update message. Any unassigned proposal additionally requires the
second `unassigned-v1` line, even if none are disabled, on both selected and relevant
actual installed companions under the existing alias guard. Direct backend commit
cannot bypass this requirement. The prior disable-only helper rejects empty
keys and restores defaults; the installed replacement supports unassignment. Existing valid assigned
data and the disabled format remain unchanged, with no TSV schema version bump.

The P1 direct-Stow bypass is resolved: selecting a source TSV beside a new helper
must not bypass an old helper for the same installed TSV. `SourceBaseline.installed_route`
captures a metadata-only `PathProof` for the actual config-root `hypr/keybindings.tsv`
with strict JSON validation. Shared resolved target or device/inode requires both
selected and actual installed companions' headers and protected proofs. The installed
route and required helpers are rechecked before state creation, under lock and before
replacement. Post-write verification permits only the selected regular leaf's own
identity change, including its aliased installed route; unrelated offline TSVs stay
independent. No main Lua reads/evaluation. Old loaders still reject the token and
select all defaults; this guard is not a future-format compatibility guarantee.

## Data Flow

Every row offers the same edit pencil, separate Disable/Enable and a dialog Enabled
switch. Clearing the Shortcut field truly unassigns regardless of that switch.
All 80 rows stay in catalog order in one Keybindings list, including blank shortcuts.
The same pencil opens the empty field for reassignment, without restoring defaults.
Pending Clear shortcut is Removed, assignment Added and Disable/
Enable Modified. Undo/Redo, Discard and per-entry Revert preserve enabled, disabled
and unassigned states. Review and independent Save write only the selected TSV.

## Example usage

To clear Super+T, close/reopen Attune. No deployment is needed. Confirm installed
default TSV (not Prepared), find Open terminal (T) / `terminal.t`, click its pencil,
clear Shortcut, choose Update Pending, Review Source Shortcuts, then Save Reviewed
Source Shortcuts. Do not apply this for the user. All 80 rows stay in order; the same
row stays blank after Save/restart and its edit dialog opens empty.
Disable remains a separate key-retaining choice.
Ctrl+S/visual Save is not source Save. Effects occur on the next configuration load,
not automatic IPC; watcher auto-reload is unproven and may occur immediately. Any
necessary manual configuration reload is the user's deliberate choice and can reset
unsaved live previews. No reload IPC was sent; live Delete behavior remains unverified.

The candidate selects **only** `$HOME/.config/hypr/keybindings-bridge.lua` and that
directory's `keybindings.tsv`. It intentionally does not search the dotfiles tree:
this avoids mixing an invalid installed pair with a different source copy or
guessing whether a directory is genuinely absent. A missing/unloadable bridge
prints a notice and uses all original source keys, callbacks and flags, with
descriptions added. Invalid/missing installed data uses the installed bridge's
embedded defaults, not any other directory's data. Callback helpers' existing
script/manager-layout fallback paths remain unchanged.

The local `source_bind(id, original_key, description, action, original_options)`
wrapper retains read-only source fallback expressions. These duplicates are
deliberate critical-key protection when the bridge is missing, not a second
editable data store. With the bridge available, it selects the validated mapping.

## Edge Cases

Valid saved data with a compatible bridge preserves both disabled and unassigned
states through Save/reopen and repeated configuration loads without default
resurrection. Missing/broken helpers and absent/invalid catalog data still select
whole defaults. This is not an unconditional guarantee under file corruption.
No callback source is removed or action deleted; normal Save does not rewrite main
Lua, evaluate authored Lua, override runtime bindings or send reload IPC.

## Deployment and rollback safeguards

The user explicitly accepted watcher/reload risk before the completed installation:
bridge first, data second, **main `hyprland.lua` last**, using individual atomic
renames, mode `0644`, with the validated hashes. Private evidence is at
`/home/jdawson/.local/state/attune-installations/source-bindings-20261102T155506Z`
(`0700` directories, `0600` files): `hyprland.lua.before`, reviewed candidate copies,
`manifest.json`, `activation.json`. Preflight main matched the frozen fixture;
bridge and data were **absent**. Unrelated `attune.lua` was untouched. Exact hashes,
symlink routing and observations are in the
[shared deployment record](../../../docs/validation.md#source-integration-activation-and-rollback).

**Writing the watched main can automatically reload Hyprland even without reload
IPC.** A bridge/data write may also be watched after installation. Main-last is
ordering guidance, not an atomic three-file installation or a no-reload promise.
Choose a maintenance/session boundary with the user before any live-path writes.
A separately approved rollback must first verify intervening changes, restore the
prior main first, then restore prior helpers or remove only introduced files whose
prior absence and unchanged installed identity are verified. Never overwrite/delete
unknown later changes. No rollback is recorded. The later compatible bridge-only
update is installed; do not repeat this original three-file deployment.
Its hashes, private backups and read-only compatibility/runtime checks are in the
[Delete-capable bridge-only record](../../../docs/validation.md#approved-delete-capable-bridge-only-deployment).
The prior helper supports Disable only, not empty keys: do not blindly downgrade after
Delete and resurrect defaults. Require fresh compatibility review and user reassignment
or a safe updated-helper plan; never restore snapshot TSV over later edits.
Terminal aliases, Wisp and volume keys still need user behavior testing. Follow the
[activation and rollback plan](../../../docs/validation.md#source-integration-activation-and-rollback).

## Offline Evidence

`tests/fixtures/source-bindings-original.lua` is the frozen pre-refactor main,
SHA-256 `f25db9b117b560a8e9ed8542be9a993be28f6990f45cdd59b9815101728c6fc4`.
`tests/test_source_bindings_equivalence.py` reads only repository fixtures and
passes their text into a subprocess sandbox. It never evaluates the real config
in an ordinary Lua environment. Its explicit environment has symbolic dispatcher
constructors and binding capture, stores startup hooks without invoking them,
and executes only native submap **declarations**, never registered callbacks.
`HOME` is virtual, runtime variables are nil, `/dev/urandom` is virtual/missing,
and mapping IO is bounded virtual text. Other file access, process execution,
writes and dispatch are forbidden. Only the allowlisted bridge text may be loaded.
Lua environment initialization is disabled (`lua -E`), with instruction/time bounds.

Tests compare all 80 keys, flags, native contexts, symbolic dispatcher arguments,
callback source text and captured upvalue values. They verify direct action-object
identity at the bridge boundary and unchanged startup-hook snapshots. Only Wisp's
five `pairs` action entries are canonicalized by ID. A reverse-mechanical text
check recovers the frozen original byte-for-byte, so nonbinding statements,
helpers, Wisp startup, and callback bodies cannot silently change. This avoids
misleading bytecode comparisons whose local indices can shift with new locals.

Coverage also includes a single edited key/description for **each of all 80 IDs**,
whole-default fallback
after an invalid file containing an otherwise valid edit, native-submap conflict
checks, missing-bridge fallback, virtual mapping-read exceptions, helper syntax
failure, sandbox side-effect refusals, and `luac -p`
syntax checks. Run only the focused test with HOME and XDG paths isolated **before
Python starts**, using the checkout's absolute `.venv/bin/python`. No callbacks,
live behavior, real startup IO, or compositor acceptance are proven by these tests.

### Historical focused checkpoint

Offline validation on 2026-11-01: **36 focused tests passed** with process HOME
and all XDG paths prepared under `/tmp/opencode` before Python started. Focused
Ruff check/fix and format passed; focused Pyright passed with the checkout's
`.venv/bin/python` explicitly selected; all three Lua files passed `luac -p`.
The full suite and repository-wide formatting/type checks were intentionally not
run under this task's focused-only, non-overlap constraints. Live validation was
not attempted.

### Delete versus Disable: final code and isolated-test validation

Historical checkpoint before the unified-list UI correction. Former Delete/Assign
New coverage and the counts below do not establish final validation of that correction.

Final full pytest: **4,361 passed, 383 skipped, 12 dependency warnings, 783.67 seconds**.
All six Broadway suites: **380 passed, 2 skipped, 6,332 dependency warnings, 138.21 seconds**.
Required Ruff `--fix`/format passed, 210 files unchanged; full-tree Pyright `--level error`
zero errors, not GI-warning clearance. Independent review found no material findings;
review-run backend/equivalence 332 passed and source GUI 82 passed. Post-review actual
mixed-state disk roundtrip (1 pass) and actual Pending Delete/key reuse/Revert (2 cases,
both modes) are included in final suites. Wheel `/tmp/opencode/attune-source-delete-dist`,
staged bridge Lua parse, installed launcher help and diff check passed.

Final suites set temporary process HOME/XDG before Python. GUI IPC was disabled,
writers mocked by default, actual publishers temporary only; daemon stopped.
The earlier non-prefixed full run (same counts, 13 warnings, 767.71 seconds) was rerun
properly; do not claim every run was process-isolated or that config writes were
established. Sentinel and live main/helper/TSV hashes stayed unchanged; all 80 mappings
are still assigned/enabled. No live data/helper/key edits, installation, reload,
shortcut invocations, Git staging or commits for this fix. These are supplied results,
not tests run by this docs pass. Those no-install statements describe code validation,
before the approved helper-only deployment; app code stayed unchanged and no full suite
was rerun for deployment.
See [final evidence and hashes](../../../docs/validation.md#source-shortcut-delete-versus-disable-implemented-and-validated).

### Historical disable-only code validation

The following counts remain historical, not the new Delete checkpoint above.

- Full-tree Ruff `--fix`/format passed, **210 files unchanged**. Full-tree Pyright
  `--level error` found **zero errors**; unfiltered GI warnings remain.
- Full pytest: **4,332 passed, 367 skipped, 13 dependency warnings**, **753.75 seconds**.
- All six Broadway GUI suites: **364 passed, 2 skipped, 5,939 dependency warnings**,
  **111.22 seconds**. IPC disabled; writers mocked by default, explicitly real source/
  managed/pair publishers temporary only; daemon stopped.
- Backend/equivalence: **304 passed**; source GUI: **68 passed**, covering Super+T
  disable, source view/flags/review, temporary Save/reopen, re-enable, combo reuse and
  atomic conflicting re-enable refusal.
- P1 regressions passed: old/missing actual helpers refuse direct writer calls before
  state/data writes, both-new success, unrelated offline editing and stale symlink/
  helper refusal. Independent source-only review confirmed P1 resolved, no blockers.
- Wheel `/tmp/opencode/attune-source-disable-dist`, updated candidate bridge `luac -p`,
  installed launcher `--help` and diff check passed. Process HOME/XDG isolated before
  Python; sentinel unchanged. No live watched files/user keys changed, no Super+T
  disable, helper installation, reload, staging or commits occurred. Unchanged final
  read-only live hashes are in the
  [validation record](../../../docs/validation.md#source-shortcut-disable-fix-implemented-and-validated).

These historical code results were not rerun for the later approved bridge-only
deployment: source code was unchanged then. Installed observation and an in-memory-only
disable review now pass without persistence; runtime metadata remains 80 bindings /
80 descriptions / zero nonblank errors. This is not live disable behavior proof or
proof that the running process loaded the new helper.

### Historical checkpoint: original key/description workflow

The following full validation superseded the focused-only limits above, not their
historical counts. These results predate disable support; the disable-only results above
validate that fix separately:

- Focused equivalence: **114 passed**, including the permanent 80-ID custom key/
  description parameterization and read-error/helper-syntax fallback cases.
- Source backend: **149 passed**.
- Full-tree Ruff check/fix and format: passed, **210 files unchanged**. Full-tree
  Pyright `--level error`: zero errors; unfiltered baseline GI warnings remain.
- Full pytest: **4,291 passed, 343 skipped, 12 dependency warnings**, **744.17 seconds**.
- All six Broadway suites: **340 passed, 2 skipped, 5,498 dependency warnings**,
  **91.35 seconds**. IPC disabled; writers mocked by default, explicit real source/
  managed/pair publishers temporary only; daemon stopped.
- Wheel `/tmp/opencode/attune-source-bindings-dist`, installed launcher help,
  read-only source worker observe/review help and diff check passed. Independent
  rechecks found no blockers after actual-config-root alias protection, immediate
  watched-TSV reload warning and Additional bindings pending navigation fixes.

Process HOME/XDG isolation preceded Python. The sandbox sentinel stayed unchanged;
dotfiles stayed unchanged except the preexisting untracked empty `attune.lua`, left
untouched with no attributed origin. Full qualifications and review fixes are in
[the shared validation record](../../../docs/validation.md#existing-source-shortcuts-current-evidence-and-limitations).

All-80 default symbolic traces and original callback-body reverse restoration are
offline evidence, not live behavior proof. That historical checkpoint made no live
writes or activation. The later approved deployment observed **80 bindings / 80 exact
catalog descriptions / zero config errors**, versus 80 / 0 / zero before, with no
missing/extra rows and unchanged keys, flags and native contexts. Installed TSV
exactly matches defaults; no user keys changed. No explicit reload IPC, callback
invocation or model-triggered key sequences were sent. Live shortcut behavior remains
user-untested, and M0 is not blanket complete. Deployment used Lua syntax checks,
hashes and read-only metadata; full-suite counts above were not rerun because app
code was unchanged. No staging or commits were performed. This documentation update
ran no commands or tests.

## Related files

- `hyprmod/core/source_bindings.py`: codec, derived enabled state, companion
  capability/proof checks, reviewed TSV publication and backups.
- `hyprmod/pages/source_bindings.py`: state-aware drafts, pending entries and controls.
- [Architecture](../../../docs/architecture.md#existing-source-shortcuts) and
  [validation](../../../docs/validation.md#existing-source-shortcuts-current-evidence-and-limitations):
  interfaces, historical evidence and outstanding activation limits.
