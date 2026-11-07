# Attune
![Attune](img/attune.jpeg)

## Overview

Attune is a personal, focused GTK4/libadwaita appearance, input and managed-keybindings editor for
[Hyprland](https://hyprland.org), forked from
[BlueManCZ/hyprmod](https://github.com/BlueManCZ/hyprmod) at `b475087`.
It previews appearance/display changes through compositor IPC; input and bindings
stay draft-only. It writes compositor configuration only after review.
The internal Python namespace remains `hyprmod` intentionally; the public launch
command is `attune`.

This fork retains the upstream attribution, including Copyright (C) 2026
Ivo Šmerek, and the **GPL-3.0-or-later** license. See [LICENSE](LICENSE).
Historical upstream releases remain in [CHANGELOG.md](CHANGELOG.md).

### Current scope

- General visual options: inner/outer gaps, border size, active/inactive border colors.
- Decoration, animations, and bezier curves.
- Monitor configuration with live preview confirmation.
- Devices: draft-only Keyboard, Mouse and Touchpad controls, 15 keys in 14 rows.
- Bluetooth: **Devices -> Bluetooth -> Open Bluetooth Manager** opens Blueman in a
  separate window for discovery, pairing and connections. Requires `blueman-manager`
  on PATH (Arch/CachyOS: install `blueman`). Attune does not install it, start services
  or change Bluetooth state itself. Blueman actions are live, not Input drafts or
  Pending Changes. Native Bluetooth controls and embedded Blueman are not included.
- Cursor: eight native controls in eight rows, implemented with final validation
  pending. Devices and Cursor share **Save Reviewed Input** to `attune-input.lua`,
  not separate saves. The user accepted the Input checkpoint and approved Cursor
  work; this does not prove live loading or device behavior. No input/cursor preview
  or mutation IPC. See [Cursor validation status](docs/validation.md#cursor-implemented-final-validation-pending).
- Attune-owned global keyboard bindings: search, add, edit, and delete local drafts,
  with separately reviewed disk persistence. Implemented and validated with automated
  and isolated GTK checks; live keyboard/loading acceptance remains unverified.
- Existing source shortcuts: edit keys and descriptions in explicitly selected TSV
  data, including the 80-shortcut catalog. The current unified list keeps every row:
  pencil -> clear Shortcut -> Update Pending -> Review Source -> Save Source leaves
   that row blank, not removed. This UI correction is implemented and validated;
  backend/schema and installed bridge are unchanged, with no deployment needed.
  User-approved three-file deployment is
  complete; all 80 runtime descriptions were observed. Live shortcut behavior still
  needs user testing. The project bundle remains a separate reference copy.
   Delete/unassignment is implemented and validated in code and isolated tests.
   The user-approved Delete-capable bridge-only deployment completed on 2026-11-03 UTC;
   the installed helper supports both Disable and unassignment. Earlier
   Disable/Enable support is implemented and validated in code through automated and
   isolated GTK checks. The user-approved bridge-only update is installed, preserving
   main Lua and TSV. All 80 rows, including Super+T, remain enabled; runtime disable
   behavior and loading of the new helper in the running process remain unverified.
- Pending Changes with an exact output diff and a separate reviewed-save action.
- Read-only output and integration information in Settings.
- Read-only Health with compositor/errors/displays, managed-output ownership,
  validator discovery, backup-candidate availability, and scalar saved/runtime drift.
- Previewable redacted diagnostics copying and explicit output/folder opening.
- Backups browser with read-only hash/canonical inspection and comparison, plus
  separately reviewed disk-only restoration of existing owned output.
- Explicit preservation-first recovery for foreign/invalid text, using a separate
  acknowledgment and verified private evidence before replacement.
- Bounded read-only startup layout assessment and a Scope Recovery page for
  separately reviewed transaction resume, rollback, finalize, and abandon.
- Explicit historical source browsing, complete both-scope reviews, and a separate
  **Commit Reviewed Historical Restore** action in Scope Recovery.

Authored Lua callbacks and live keymaps remain untouched. The narrow user-approved
exception is the authored integration and its separately user-approved deployment, not an application main-Lua
writer. Explicitly selected source metadata is editable as described below.
Runtime bindings are read-only observations,
not evidence of their source or of Attune output being loaded. Workspaces, layouts,
rules, autostart, environment, plugins, and other hand-authored behavior stay outside
the editor. There are no profiles or profile CLI,
automatic saves, startup reloads, main Lua parsing, configuration migrations, or
automatic include insertion in the focused application. Launching does not silently
register a desktop entry.

**Existing registered canonical-pair editing is implemented and validated.**
The normal editor can read, edit, review, Save, and continue editing
an already registered v2 appearance/display pair through the mature journaled
writer. The `legacy-clear` v1 `attune.lua` workflow remains unchanged.
This visual-pair workflow is not installation or migration: it creates no registry,
initializes no transaction store, provisions no missing/empty scope target, and edits
no loader lines. Independent bindings and Input writers can create their own private state.
See [ADR 0001](docs/decisions/0001-shared-local-ownership.md).

### Roadmap

Additional managed bindings have an automated validated checkpoint, but useful
editing of existing bindings remains the priority until live behavior is accepted.
The source-aware integration is deployed with runtime metadata verified. Device/Input
has a historical offline-validated checkpoint accepted by the user. Cursor work was
then approved and is implemented, pending final validation. Rules, startup and
environment remain separately scoped later work, not automatic expansion. Profiles
and layout pages remain out of scope. Manual acceptance remains necessary, but
migration and automatic scoped foreign-file preservation are deferred and nonblocking,
not prerequisites for managed bindings or Device/Input.
Diagnostics, explicit transaction recovery, and canonical historical restore are
already implemented; they are support features, not an open-ended recovery-foundation
milestone. M0 live acceptance remains pending, requiring separate user confirmation.
See [ROADMAP.md](ROADMAP.md) and the short [manual checklist](docs/validation.md#manual-acceptance-checklist).

## API / Interfaces

### Existing source shortcuts

**Current UI:** one **Keybindings** list keeps all 80 catalog rows in stable order.
Every pencil opens **Edit Source Shortcut**, including rows with no shortcut.
There is no Delete button, Assign New action or Unassigned expander. To unassign,
clear **Shortcut** -> **Update Pending** -> **Review Source Shortcuts...** ->
**Save Reviewed Source Shortcuts**. The row stays in place with a blank shortcut
after Save/restart; reopening its pencil shows an empty field. Pending labels this
**Clear shortcut**, not Delete. Disable instead keeps the assigned key stored and off.
Use the actual installed default `/home/jdawson/.config/hypr/keybindings.tsv`, not
Prepared. The existing backend and installed unassignment-capable bridge already
support this; no deployment, schema or state change is needed. The UI correction is
implemented and validated: full pytest **4,361 passed, 383 skipped**; all six isolated
Broadway suites **380 passed, 2 skipped**. See [current UI validation](docs/validation.md#ui-only-correction-final-validation)
for supplied final results and limits. Earlier counts below retain their historical scope.
Entering a key in an empty row defaults Enabled on; live behavior remains unverified.

The pre-deployment live inventory had **80 `__lua` bindings and zero descriptions**.
Its numeric `arg` is a Lua registry reference, not source code or a source line.
Read-only opaque rows alone therefore do not provide a useful existing-shortcut
editor. Runtime descriptions are preferred when provided, but none were available
in that observation. After the approved 2026-11-02 deployment, read-only inspection
found **80 bindings with 80 exact catalog descriptions and zero config errors**, with
unchanged keys/flags/native contexts. This is metadata activation, not live action
acceptance. Attune does not execute authored main Lua to recover actions.

Close/reopen Attune, then **Keybindings -> Existing shortcuts** uses the installed
default `/home/jdawson/.config/hypr/keybindings.tsv`; installed-path observation
succeeded with 80 rows. **Open Prepared Source Mappings** is only needed for preview:
it opens
`integrations/hyprland/jdawson/keybindings.tsv` in this checkout now. It does not
copy/install files or require live activation. **Open Source Mappings...** selects
another existing file named `keybindings.tsv`; the initial declared path is
`$XDG_CONFIG_HOME/hypr/keybindings.tsv` (`~/.config` fallback).

`key`, `description` and assignment/enabled state can change. `SourceBinding.assigned`
means `key != ""`; `enabled` means assigned and not metadata-only `disabled`. The v1
marker and all-enabled bytes stay unchanged. Stable IDs, descriptive context, native
submap, base flags and catalog order remain fixed; callbacks are not data or editable.
All 80 declarations remain present, not necessarily 80 assigned bindings.

| State / action | Stored key | `disabled` marker | After Save and normal restart with compatible bridge |
| --- | --- | --- | --- |
| Enabled assignment | Nonempty | Absent | Remains assigned and enabled |
| Disable | Nonempty key retained, off | Present | Remains assigned and disabled; Pending is Modified |
| Clear Shortcut field | Exactly empty; old key value removed entirely | Absent | Same row remains blank; Pending Clear shortcut (Removed) |

Clearing the dialog's **Shortcut** field truly unassigns: the saved
row has an exactly empty key and no `disabled` token, not the old combo or an off
tombstone. Empty plus `disabled` is invalid. The action/description stays in the
same position in the unified **Keybindings** list, with a blank shortcut, not the
old/default key. **Disable/Enable** and the dialog's **Enabled** switch
are separate: Disable retains the assigned key. Pending Changes marks Clear shortcut as
Removed, assignment as Added and Disable/Enable as Modified. Undo/Redo, Discard and
per-entry Revert preserve all three states: enabled, disabled and unassigned.
Disabled combinations are free for another enabled source shortcut in the same
native submap. Re-enabling a conflicting combination refuses before changing the draft.
Search covers descriptions, keys, IDs and context. **Review Source Shortcuts...**
shows the complete TSV diff, lexical/resolved paths and hashes; the separate
**Save Reviewed Source Shortcuts** writes only that selected metadata file.
Source, **Additional bindings** (`attune-bindings.lua`), Input (`attune-input.lua`),
and appearance/displays are four independent save units with separate dirty baselines and undo retention.
There is no atomic Save Everything. Source uncertainty locks only source editing.
The actual config root's main/generated/registry routes are protected by metadata-only
alias checks independently of the selected TSV's location, including Stow sources.
Saving an **already-integrated or watched TSV may trigger an immediate reload**;
Attune sends no reload IPC and does not install a loader.

The reference bundle contains `hyprland.lua`, trusted bridge, and 80-row TSV.
Earlier reviewed copies were installed through the preserved Stow route; the
unassignment-capable bridge-only update is now installed. The project directory
is not directly loaded. Callback bodies and definition sites remain
unchanged, with description options added to registrations. The bridge validates the whole
catalog before registration or uses **all** embedded defaults; a missing/unloadable
bridge uses original source keys/actions/flags with descriptions. TSV is data, not
evaluated Lua, and the bridge needs no JSON library. Existing generated managed
formats remain unchanged.

**Compatibility and activation limit:** the unassignment fix is implemented and
validated in code and isolated tests, not live. Existing valid assigned data and
the disabled format remain byte-unchanged; there is no schema version bump.
The candidate bridge retains the first capability line below and adds the second:

```lua
-- Attune source bindings capabilities: disabled-v1
-- Attune source bindings capabilities: unassigned-v1
```

Any proposed empty key requires both ordered headers on the selected companion and,
when the existing alias guard applies, the relevant actual installed companion.
Review and direct backend commit block unsupported helpers with an update message.
The installed `1d1023aa...` helper supports both capabilities; it replaced disable-only `0fc1fa9f...`.
Valid saved data with a compatible bridge preserves unassignment across reopen and
configuration loads without default resurrection. Missing/broken helpers or invalid
catalog data still select whole defaults; this is not corruption-proof persistence.

Old all-enabled data is readable by old and
new bridges. An old bridge cannot honor `disabled` and would fall back to **all 80
defaults**. Review and commit therefore block any
proposal containing disabled rows unless the selected TSV's companion bridge has
the first-line capability `-- Attune source bindings capabilities: disabled-v1`
and matches its captured path proof. Selecting a direct Stow/source path cannot
bypass the installed helper: if the selected TSV and actual config-root TSV share
a resolved target or device/inode, **both** selected and installed companions must
pass. `SourceBaseline.installed_route` binds that installed TSV route through strict
JSON transport and writer rechecks. Unrelated offline TSVs remain independent.
Old/missing helpers report:
"Update the source keybindings bridge before saving disabled or unassigned shortcuts
(requires disabled-v1 and unassigned-v1); older bridges would restore defaults."
The requirements message names only `disabled-v1` for disabled-only proposals.
The user-approved **bridge-only update is installed** (2026-11-03 UTC), preserving
main Lua and TSV. Installed-path observation and separate in-memory-only `terminal.t`
Delete and Disable reviews passed without persistence at that historical checkpoint;
the recorded TSV remained all 80 enabled.
Unchanged runtime metadata does not prove the running process loaded the new helper.
The prior disable-only bridge cannot accept empty keys: do not blindly downgrade after
Delete and resurrect defaults. Rollback needs fresh compatibility review and user
reassignment or a safe updated-helper plan; never overwrite later TSV edits with
a snapshot. See the deployment record for hashes, private evidence and safeguards.

See [the source contract](docs/architecture.md#existing-source-shortcuts) for limits
and backups, and [activation/rollback instructions](docs/validation.md#source-integration-activation-and-rollback).
All-80 runtime descriptions are observed; shortcut behavior remains user-untested.
Isolated registration equivalence is not callback/live behavior proof.

**Historical Delete code validation (before the UI correction):** full pytest **4,361 passed, 383 skipped** and all six isolated
Broadway suites **380 passed, 2 skipped**. Required Ruff/format and error-level
Pyright passed; independent review found no material findings. See
[final Delete validation](docs/validation.md#source-shortcut-delete-versus-disable-implemented-and-validated)
for timings, warnings, isolation qualifications and unchanged live hashes. This
docs-only pass records supplied results and ran no checks.

Historical disable-only counts remain **4,332 passed, 367 skipped** (full), **364
passed, 2 skipped** (six GUI suites), **304 passed** (backend/equivalence), and **68
passed** (source GUI). Their checks, P1 review, timings and activation limits remain
in the [historical record](docs/validation.md#source-shortcut-disable-fix-implemented-and-validated),
alongside the earlier key/description-only checkpoint, not as new Delete validation.

### Managed keybindings

**Keybindings -> Additional bindings** edits only `$XDG_CONFIG_HOME/hypr/attune-bindings.lua` (default
`~/.config/hypr/attune-bindings.lua`). It is available in both admitted legacy and
existing-pair editors, without migration, registry creation, or a new visual scope.
Its `-- Attune bindings data v1: ` record is a distinct bindings format, not visual
v1 `attune.lua` or scoped visual v2. Nonempty content must regenerate byte-exactly;
foreign, manually edited, or unknown-format output blocks editing and requires
manual remediation. There is no automatic import or overwrite exception.

- Search covers shortcuts, actions, categories, and origin labels. Add/edit uses a
  draft-only dialog; delete removes only an owned generated directive. Supported
  global keyboard types are `bind`, `binde`, `bindl`, `bindr`, and `bindn`.
  Mouse/keycode/catchall triggers, submaps, and other variants are not managed.
  An owned action the dialog cannot represent has no Edit button, but can be deleted.
- All reported runtime entries, including opaque Lua callbacks, are read-only.
  Matching a saved shortcut proves neither origin nor loading. Flags shown are
  those exposed by the installed client model, not a complete Lua-flag inventory.
- New or moved combinations are blocked when they overlap the observed runtime
  inventory; duplicate owned combinations are rejected. Editing an existing owned
  row without changing its combination remains local and is allowed with an
  unknown-origin overlap warning. Offline, failed, or empty runtime inventories
  are **unknown**, never a claim of conflict freedom. The inventory is a snapshot,
  not continuous conflict monitoring or a save-time runtime recheck.
- Shortcut recording receives GTK events only. Reserved compositor shortcuts may
  never reach it; use **Manual Edit** instead. No grab, unbind, override, live apply,
  reload, or main-Lua read is performed by this workflow. Runtime queries are read-only.
- Command actions must be proven to emit the exact original command literally.
  Library rewrites of `exec`/`execr` are rejected with actionable guidance, not
  silently translated. Raw command is an option only if that behavior is intended.
  Literal-proven `$`, quotes, commas and shell operators remain supported.
- Shortcut-only edits preserve exact arguments, using plain text when a structured
  control would default or clamp them. Revert can restore the owned saved combination
  despite runtime overlap, but cannot introduce a duplicate owned combination.

Ctrl+S opens Pending Changes. **Save Reviewed Keybindings**, **Save Reviewed Input**,
**Save Reviewed Source Shortcuts** and **Save Reviewed Appearance / Displays** are independent save units,
not an atomic Save Everything.
Each successful save adopts only its verified baseline and clears only its own
undo history; all other units' drafts, saved baselines and undo history remain. Changed drafts
invalidate review. Appearance/display save behavior below is otherwise unchanged.

Bindings review shows exact prior/proposed bytes, paths and hashes. Save rechecks
the fixed route, protected paths and source under its dedicated
`$XDG_STATE_HOME/attune/bindings.lock`, compile-checks Lua without executing it,
backs up existing prior bytes to private
`$XDG_STATE_HOME/attune/bindings-backups/<sha256>.lua`, then publishes and verifies
the result. No pair journal is used. Safe existing file/parent Stow links are
preserved; the resolved basename must also be `attune-bindings.lua` and its safe
owned writable parent must already exist. Absent or empty targets are supported;
dangling links, hardlinks, unsafe paths and protected-path collisions are refused.
State/backups must be outside Git; output may be in dotfiles. Save runs directly on
a non-daemon worker with writer exclusion and close veto. Uncertain publication or
failed baseline adoption retains the draft and locks the bindings unit, not the
visual unit. Inspect disk and reopen; no automatic recovery is offered.

Earlier additional-bindings checkpoint: full pytest **4,026 passed, 299 skipped**; all five isolated Broadway
suites **296 passed, 2 skipped**, with IPC disabled. Required Ruff/format and
error-level Pyright checks, build and help checks passed. These are not live
keyboard or loader semantics checks. See [the validation record](docs/validation.md#managed-keybindings-implemented-and-validated)
for warnings, review fixes, and the unexplained empty-file observation during the
initial run. These counts do not validate the new source-aware feature.
Earlier pair-editor counts remain historical.

### Devices / Input

**Historical Devices-only offline checkpoint, now accepted by the user.**
Its final results were full pytest **4,632 passed, 483 skipped**; eight isolated
Broadway suites **480 passed, 2 skipped**. Ruff/format, error-level Pyright, wheel,
help and parent diff checks passed; independent backend/UI review found no remaining
material findings. See [final evidence and limits](docs/validation.md#deviceinput-validated-offline-user-acceptance-pending)
for timings, warnings and isolation. These results do not validate the Cursor
extension or prove live loading/device behavior. Cursor final validation is pending.
The **Devices** page exposes Keyboard, Mouse and Touchpad in admitted legacy and
existing-pair editors. Its 15 managed keys occupy 14 rows because keyboard layouts
and variants share one paired editor:

| Section | Managed keys (under `input:`) |
| --- | --- |
| Keyboard | `kb_layout` + `kb_variant`, `kb_options`, `numlock_by_default`, `repeat_rate`, `repeat_delay` |
| Mouse | `sensitivity`, `accel_profile`, `left_handed`, `natural_scroll`, `scroll_factor` |
| Touchpad | `touchpad:natural_scroll`, `touchpad:tap-to-click`, `touchpad:disable_while_typing`, `touchpad:scroll_factor` |

`kb_options` is raw comma-separated XKB text: syntactically admitted unknown tags
are preserved, not filtered through a known-options picker. Repeat rate is 0–200,
delay 0–2000, sensitivity -1–1, and acceleration is empty, `flat` or `adaptive`.
Both scroll factors are conservatively **0.1–2.0 in 0.1 steps**, not an unverified
maximum of 10. These validation ranges do not establish live compositor semantics.

Opening the page creates no overrides. Owned saved values take precedence;
unmanaged controls show labeled read-only runtime hints when available, otherwise
defaults, not proven device state. Edits, Undo/Redo, Reset and Discard remain local.
Reset removes an override; Discard restores its saved state. Layout/variant edits,
Reset and Discard operate together as one undo action. Each row visibly identifies
Saved override, Draft override, Current runtime snapshot or Default, not observed.
Unapplied keyboard-options text survives unrelated edits and is labeled **Unapplied
text (not in draft)**; use its Apply action to enter it into the draft before review.

Ctrl+S prepares the complete combined Devices/Cursor diff. **Save Reviewed Input** writes only
`$XDG_CONFIG_HOME/hypr/attune-input.lua` (`~/.config` fallback), a typed closed
`-- Attune input data v1: ` format, separate from shared appearance and visual v1/v2.
Nonempty output must regenerate byte-exactly; foreign, manually edited or unknown
content blocks editing. There is no automatic import, repair, loader/include
insertion, input preview, mutation IPC or reload.

The safe owned writable parent must already exist. Safe existing Stow links are
preserved; the resolved basename must remain `attune-input.lua`. It may resolve to
a Linux Git/Stow source, but remains a separate machine-side file: the user decides
what to commit, and Attune never stages it. Private state stays outside Git at
`$XDG_STATE_HOME/attune/input.lock` and `input-backups/<sha256>.lua`. Save uses fresh
route/byte checks, compile-only Lua validation, a direct non-daemon writer, global
writer-owner exclusion and close veto. Uncertain publication or failed adoption
retains the draft and locks both Devices and Cursor as one Input unit, without
discarding other units' drafts.
Verified success supports another edit/review/Save and reopening in either editor.
Sequential saves retain each other unit's own source baseline, draft and undo.
A new review may refresh only safe known sibling-output regular/absent leaf proofs;
own source/Git evidence, paths, symlinks, ancestors, main/bridge/registry and the
source installed route remain strict. Writers require the complete exact reviewed
evidence under lock and before replacement: a post-review change invalidates Save,
not silently rebases it. Only that unit's verified result becomes its new baseline.

No profiles, window layouts, per-device hardware matching, global device-disable
control or keymap-file editing is added. Touchpad disable-while-typing is not device
disable, and touchpad settings may have no effect without a touchpad. See the
[Input contract](docs/architecture.md#devices--input) and
[user acceptance checklist](docs/validation.md#deviceinput-validated-offline-user-acceptance-pending).

### Cursor

Cursor exposes only the following native `cursor:` options in admitted legacy and
pair editors. Final validation is pending; this is not a live acceptance claim.

| Key | Type / allowed values | Default |
| --- | --- | --- |
| `no_warps` | Boolean | `false` |
| `persistent_warps` | Boolean | `false` |
| `warp_on_change_workspace` | Integer: 0 Disable, 1 Enable, 2 Force | `0` |
| `zoom_factor` | Finite float, 1–10 | `1.0` |
| `inactive_timeout` | Finite float, 0–20 seconds; 0 never hides | `0.0` |
| `hide_on_key_press` | Boolean | `false` |
| `hide_on_touch` | Boolean | `true` |
| `hide_on_tablet` | Boolean | `false` |

Zoom and timeout use locale-aware numeric entries with explicit **Apply** and
round-trip float display, without a one-decimal restriction or GTK spin rounding/
epsilon. The +/− buttons use decimal arithmetic to step by 0.1 and apply. Typed
text stays outside the draft/review until Apply and survives unrelated edits and
Undo/Redo; whole-unit Discard and saved-baseline adoption replace it authoritatively.
Backend floats may be any finite value within bounds, without a grid restriction;
the public library emission proof can still reject unrepresentable precision
rather than rewrite it. Types, defaults
and ranges were checked against `hyprland-schema` 0.7.1's Hyprland v0.56.1 bundle
and the matching [upstream source](https://raw.githubusercontent.com/hyprwm/Hyprland/v0.56.1/src/config/values/ConfigValues.cpp),
not every running version or actual device state.

Opening either view creates no overrides. Both share one draft, baseline, read-only
observation and undo owner. Saved/Draft/Runtime/Default labels describe origins,
not proven loading. Search, Pending navigation and sidebar badges distinguish the
views, but Input dirty state is counted once. Editing either invalidates the full
combined review. **Save Reviewed Input** saves both views and adopts their shared
baseline; whole-unit Input Discard restores both. Per-row Discard affects that row.
There is no Cursor-only save or fifth output. The other three units retain their
drafts, baselines and undo.

The closed Input allowlist is now 23 keys. Existing Devices-only canonical bytes
and the input v1 record remain unchanged, but older Attune rejects the new Cursor
keys: this is not downgrade compatibility. Theme/size, environment, `set_cursor`,
GSettings, hardware and rendering controls are excluded; the inherited theme picker
remains inactive. See the [shared architecture contract](docs/architecture.md#cursor-shared-input-view)
and [limited acceptance checklist](docs/validation.md#cursor-implemented-final-validation-pending).

### Existing canonical-pair editor

Startup admits `pair-ready` only for two existing, correctly scoped canonical v2
outputs at explicit registry routes, a safe initialized private store, and a full
bounded scan verifying all journals are terminal and intact. Zero journals are
allowed. Old terminal transactions need not match today's output bytes: recovery
`LayoutAssessment` row `actual_status` conflicts are not editor readiness criteria.
Pending/corrupt evidence anywhere, including beyond displayed recovery rows, blocks
entry. `legacy-clear` still selects v1; other outcomes fail closed into recovery.

The normal scalar, animation/Bezier, and monitor pages use session-local pair
models, not the v1 cache. Only dirty values/sections become proposals; untouched
saved records and omitted sibling bytes remain intact. Ctrl+S prepares a bounded
asynchronous **CURRENT -> GOAL** review for both scopes, including paths, hashes,
content IDs, and precomputed diffs. Further edits invalidate that review.

**Save Reviewed Appearance / Displays** publishes exactly that review on a direct non-daemon
worker with writer exclusion and close veto. Changed saves use a new transaction.
Success re-reads a fresh safe pair and checks exact reviewed goals and route bindings
before marking UI state saved, so a second Save works without restarting. Failures
retain dirty edits; uncertain output/journal outcomes or failed post-save verification
lock the editor rather than adopting an unverified baseline. Retry review for temporary
failures only. If disk files/routes changed, manually correct or restore the registered
canonical files/routes, then restart/reopen Attune: the original pair baseline cannot
adopt external edits. Retained edits are session-local, not saved across restart.
Save sends no reload IPC; watched files may nevertheless auto-reload.

Settings shows registered/resolved pair routes. **Health** and **Backups** remain
legacy-v1 utilities, not pair health or v2 backup browsers; Settings labels this
limitation. Scope Recovery provides explicit transaction recovery and canonical
historical restore separately.

If entry is blocked, keep original files and private evidence. For pending work,
use Scope Recovery to refresh, review an allowed action, then explicitly commit.
For foreign/invalid/wrong-scope/missing output or a missing/unsafe store, inspect
the reported registry/routes/store outside Attune and manually restore a verified
canonical pair and safe initialized store, then **Retry Startup Check**. Corrupt
evidence requires manual investigation, not deletion to bypass the gate. No automatic
overwrite, permission repair, store initialization, or foreign preservation is offered
for scoped files.

### Local source setup and launch

Use this checkout, not the upstream curl installer or an upstream `hyprmod` package.
`install.sh` is deliberately disabled: every invocation prints guidance and exits
nonzero without installing, uninstalling, downloading, or registering anything.

Requirements: Python 3.12+, `uv`, GTK4, libadwaita, Cairo, GObject introspection
development support, and Lua (`luac` or `lua` on PATH for save validation).
PyGObject and pycairo are resolved by the project environment but need native
libraries to build and run. On CachyOS/Arch, relevant native packages include
`gtk4`, `libadwaita`, `cairo`, `gobject-introspection`, and `lua`.
A running compatible Hyprland Lua session is needed for full live preview and
persistent integration; offline operation cannot verify compositor behavior.

From the checkout on this CachyOS machine:

```bash
cd /home/jdawson/Projects/attune
uv sync --python /usr/bin/python3
uv run attune
```

The project environment has already been created locally. To launch it without
uv on PATH:

```bash
~/Projects/attune/.venv/bin/attune
```

To copy that development launcher into `~/.local/bin`:

```bash
make install
attune
```

`make` and `make install-dev` do the same installation. This copies the console
entrypoint, not a standalone application: keep this checkout and its `.venv` in
place. Python source edits remain visible through the editable environment.
Installation does not register a desktop entry or change Hyprland configuration.
Override the destination with `make install BINDIR=/path/to/bin` if needed.

If the environment has not been prepared, run `make build` first. This uses
`uv sync --locked --python /usr/bin/python3`; `UV`, `PYTHON`, and `VENV` are
overridable. With the temporary uv executable available here:

```bash
make build UV=/tmp/opencode/uv/uv
make install
```

Use the system interpreter through a uv-managed project environment, not a system
`pip` installation. The `uv` currently available for this machine's setup is
temporary at `/tmp/opencode/uv/uv`, not a permanent installation. If `uv` is not on
PATH, substitute that absolute path in both commands while it exists. Arrange a
permanent uv installation separately if desired; this project does not bootstrap it.

Normal launch does not register a launcher. The entrypoint retains explicit
`--install` / `--uninstall` desktop-integration actions for deliberate use, but
they are not part of this local-source workflow. There is no profile command.

### Read-only Health

Select **Health** in the sidebar. The first visit collects observations; **Refresh**
requests another snapshot. There is no background polling or automatic repair.
Each check shows its own status and details, with the observation time above.
If a refresh fails, an earlier snapshot remains visible and is labeled stale.

The collector queries `hyprctl -j version`, `configerrors`, `monitors`, and
allowlisted `getoption KEY` requests for saved scalar drift. It inspects the
dedicated Attune output, locates a Lua validator without running it,
and counts candidate backup files. It does not execute Lua, create configuration
or state directories, reload Hyprland, or apply settings. File presence does not
prove runtime loading; backup candidates are not verified as restorable.

Refresh runs outside the GTK thread in a supervised child process. Queries have
two-second deadlines and bounded output; the whole collector has a ten-second
deadline. Closing its window requests cancellation without waiting on the UI
thread. Responses may be explicitly truncated to keep the view bounded.

If a foreign or invalid managed file prevents editor startup, choose **Open Health**
from the recovery screen. **Back** returns to **Retry Startup Check** without weakening the
foreign-file overwrite guard. Copy/export, saved/runtime drift comparison, and
output-opening actions are available in both views:

- **Preview Report** shows a frozen, redacted summary. **Copy Report** copies exactly
  that preview; Cancel copies nothing. Raw errors, paths, configuration, display
  identities, and drift values are omitted. Inspect before sharing: the remaining
  software versions/counts/timestamps are not guaranteed to be anonymous. Export is
  clipboard-only; no report file is created. A retained stale observation is labeled.
- **Saved / Runtime Drift** compares supported scalar values from canonical owned
  output, normalizing numbers, booleans, gap shorthand, vectors, and gradients.
  There is a shared two-second/32-query budget; unsupported or unobserved entries
  are explicitly unknown. It does not compare monitor/animation definitions or
  Beziers, infer authored fallbacks, establish that output is loaded, or repair
  differences. Last-save metadata is not recorded and is not inferred from mtime.
- **Open Output** uses the configured `text/plain` application, not the Lua MIME
  association. **Open Folder** uses the directory handler. Both use asynchronous
  native URI dispatch after checking the target type. Missing files/folders or
  applications produce an error without creating anything. Your default editor
  and file manager are part of the local OS trust boundary.

### Backups and reviewed disk restoration

Select **Backups** in the sidebar, or **Legacy Backups (v1)** on the startup recovery
screen. The first visit loads the configured backup directory; **Refresh** requests
another observation. Missing directories remain missing and show an empty result.
Backups appear only after prior nonempty output has been backed up by a save.

Rows show full hash identities, canonical counts, byte sizes, and filesystem
modification times. Ordering is lexical by hash, not save history, and modification
time is not a last-save timestamp. **Valid** means the bytes match the filename's
SHA-256 and Attune's canonical format; it is not proof of Lua syntax, compositor
acceptance, or safe restoration. Invalid/unavailable rows explain their condition
and cannot be selected for comparison.

Choose **Compare** on a valid row to view **BACKUP -> CURRENT**. Selection re-reads
and verifies the backup rather than trusting the earlier row. Readable foreign or
invalid current output is labeled and compared as raw UTF-8 without executing it
or making it writable. A missing current file in an accessible parent compares
against empty content; inaccessible, dangling, binary, or nonregular targets show
an error. Differences are local inspection, not a restore proposal or live state.

Inspection and diff computation run in supervised child processes with ten-second
deadlines and cancellation on closure. Listing examines at most 1,000 directory
entries, 64 hash-named candidates, and 16 MiB of file data, with 1 MiB per file.
Comparison admits 256 KiB/10,000 lines per side. Rendered diffs are capped at
256 KiB/4,000 lines and 4,096 bytes per row. Omissions, oversized inputs, and
truncated results are explicitly labeled; line counts cover admitted full inputs.
These limits can prevent showing the full diff of a long canonical data-record line.

Only one list/compare/preparation operation runs per page. Refresh clears the prior diff;
failed refresh retains stale rows with comparison disabled. No polling, restoration,
deletion, export, Lua validation/execution, compositor commands, or configuration
changes occur through the inspection-only Compare action.

**Review Restoration** is a separate action on valid rows:

1. Finish or discard pending editor changes and resolve any monitor preview.
2. Choose Review Restoration. Read-only preparation validates both the backup and
   current output, compile-checks Lua without executing it, and binds exact bytes,
   hashes, source root, and lexical/resolved destination into an immutable draft.
3. Inspect the complete **CURRENT -> BACKUP** diff. This is the reverse direction
   from inspection. Cancel writes nothing. Oversized restoration reviews are
   refused rather than truncated.
4. Only **Restore Reviewed Output** enters the protected writer. It rechecks the
   draft, source, current bytes, and destination; backs up the previous output;
   and atomically replaces the resolved file while preserving Stow links.
5. After success, note the rollback backup path and restart Attune before editing.
   The old cached editor is disabled, not silently marked saved. Health, Backups,
   and Settings remain available. An uncertain write outcome also locks the editor
   and requires inspection/restart. An unchanged result writes nothing.

Restoration currently requires existing, nonempty canonical owned output. It
refuses foreign, missing, empty, invalid, and unsafe targets. Every attempt consumes
the draft; changed files/paths or errors require a fresh review. No restore CLI or
general foreign-file overwrite exception is exposed. The explicit recovery path
below is separate from ordinary saves and restoration.

**Disk-only does not guarantee unchanged live state:** Attune sends no reload or
live-apply commands, but Hyprland may auto-reload a watched file after replacement.
Explicit live preview/application remains separate roadmap work.

Preparation is supervised with a 30-second deadline. Each side is limited to
256 KiB/10,000 lines; the complete review to 256 KiB/4,000 lines. Commit runs on a
non-daemon worker, never a timeout-killed process. Lock acquisition has a five-second
limit and each compile check a ten-second limit; these are not a hard total bound
for arbitrary filesystem I/O. Closure is held until the commit outcome, without
joining on GTK. Failures before replacement may still leave a lock or rollback
file; they are not described as transactional cleanup of all side effects.

### Preservation-first text recovery

When current `attune.lua` is foreign or has invalid Attune data, **Review Recovery**
is distinct from Compare and Review Restoration. It is available on valid backup
rows, including in startup recovery. Owned output must use ordinary restoration;
recovery does not silently run after another action fails.

1. Choose Review Recovery. Read-only preparation verifies the selected canonical
   backup and captures the exact current text without executing or compiling it.
2. Inspect the complete **CURRENT -> RECOVERY BACKUP** review, including source and
   current hashes, resolved destination, original status, and preservation path.
3. Acknowledge replacement and possible watched-file auto-reload. Only then can
   **Preserve and Recover Reviewed Output** start the protected writer.
4. Before replacement, Attune exclusively creates or verifies the exact original
   bytes under `$XDG_STATE_HOME/attune/preserved/<sha256>.bin`, with private owned
   `0700` directories and a `0600` file. It verifies bytes/hash and synchronizes
   the evidence file and directory. Unsafe permissions or preservation failure
   prevent output replacement; existing user permissions are not silently changed.
5. Success reports the preserved-original path. Keep it for manual inspection;
   it is not a canonical backup or a promise of safe executable rollback. Restart
   Attune before editing. Uncertain outcomes also invalidate the cached editor.

Recovery shares restoration's dirty/monitor gates, one-use review, source/path
rechecks, direct non-daemon writer, and close protection. Cancel before commit
writes nothing. Failures may leave private evidence or state files even where no
output replacement occurred. Ordinary saves still reject foreign/invalid content.

This version only supports existing nonempty UTF-8 text within 256 KiB/10,000 lines,
with a complete review fitting 256 KiB/4,000 lines. Binary/control content, missing,
empty, oversized, unsafe, or main-config-alias targets fail closed. Only the
canonical candidate is compile-checked; the original is preserved as raw evidence.
No live-apply/reload commands or general recovery CLI are added. Hyprland's own
watcher may nevertheless auto-reload the replacement.

### Scope Recovery and legacy exclusion

Startup first shows **Checking Attune Layout**. Its bounded, read-only editor-entry
inspection creates or repairs no state. `legacy-clear` constructs the v1 editor;
`pair-ready` constructs the canonical-pair editor described above. Blocked observations and errors open the
recovery shell with **Scope Recovery**, **Legacy Backups (v1)**, **Open Health**,
and **Retry Startup Check** instead. This does not select a runtime loader.

In Scope Recovery, refresh the assessment, choose a transaction and **Review
resume**, **Review rollback**, **Review finalize**, or **Review abandon**. The
backend refuses actions incompatible with actual bytes, locked rollback direction,
or terminal/conflicting evidence. Inspect the complete **CURRENT -> GOAL** review
for both appearance and displays, including unchanged scopes, paths, hashes,
content IDs, and review/private-evidence identities. Only the separate **Commit
Reviewed Scope Recovery** action writes. Canceling assessment/review writes nothing.

Editor entry uses a 30-second isolated read-only worker. The separate recovery
assessment/review workers default to 15/30 seconds; assessment displays at most 32
transaction rows. That display cap is not the full editor-entry safety scan.
Commits run directly on non-daemon workers,
not timeout-killed children. Close requests are vetoed while writing. Owner-aware
exclusion prevents legacy restoration and scope recovery from overlapping or
releasing each other's writer gate. Pending editor changes and monitor previews
block recovery. Scope or journal uncertainty independently invalidates caches and
locks the old editor without marking its baseline saved. Refresh and prepare a
fresh review before another action.

Any installation registry or transaction evidence, including terminal history,
blocks v1 save, restoration, and preservation-first replacement. Unsafe or
uninspectable metadata fails closed, not back to v1. The writer rechecks this
exclusion independently of startup. Legacy backups remain inspectable full bundles;
they are not implicitly converted or restored into a v2 scope. Automatic scoped
foreign preservation is deferred, not a migration prerequisite. B1 provides canonical
preparation; b2 adds **Browse Historical Sources** only on explicit user request,
never during startup or as provisioning. The listing safety-checks all journals
within the 1,000-entry limit, displaying at most 32 transactions with four sources
each: appearance/displays, prior/proposed. Display truncation alone does not mean
an incomplete scan. Pending/corrupt evidence anywhere blocks all source reviews;
an incompatible historical route blocks only that row when global inspection is safe.
An old terminal transaction's recovery `actual_status=conflict` is not its historical
source eligibility.

Choose **Review appearance prior** (or another eligible scope/side) to inspect the
complete **CURRENT -> GOAL** pair, retaining the current sibling unchanged. A safe
initialized store, canonical current pair, matching registry/roots, and historical
both-route bindings are required. Phase and hashes prove neither installation of
either side, runtime loading, Lua/compiler validity, nor authentication. Historical
reviews cannot populate the transaction recovery draft or enable its commit button.
Only **Commit Reviewed Historical Restore** consumes the separate `ScopedRestoreDraft`;
browsing or preparing a review never implicitly commits. Assessment, listing, and preparation share one
asynchronous read-only slot, retained through cancellation cleanup. Listing/preparation
children default to 30-second deadlines with 1 MiB/8 MiB transport limits respectively.
See [the browsing/review API contract](docs/architecture.md#m36b2-historical-source-browsing-and-read-only-review)
and its b1 preparation contract above it.
The explicit backend `scoped_restore.commit_restore(draft, cancel_event=...)`
can write the selected canonical scope through a new ordinary transaction. It
rechecks the complete historical source and current review under lock throughout
publication, preserves the current sibling and Stow links, and leaves source
evidence unchanged. It is a direct non-daemon mutator, never a timeout-killable
child or CLI command. No-op commits still validate and compile-check, but create
no journal or stages; a lock file may be created. Failures may leave a new pending
transaction requiring a fresh explicit existing-recovery review, never source replay.
Backend uncertainty flags are returned unchanged; callers must invalidate stale
editors. The GUI rechecks dirty/monitor-preview permission and writer exclusion,
consumes reviews and action rows, and holds closure until its direct worker completes.
It validates exact typed results, transaction identities, and flags; invalid results
or exceptions after delegation conservatively set both sticky uncertainty flags.
A worker start failure before delegation adds no uncertainty. Matching-owner release
and sticky editor locking precede fallible cache/widget notifications. No old baseline
is marked Saved. Outcomes distinguish the historical source from the new restore
transaction; a pending new transaction needs **Refresh Scope Assessment**, a fresh
recovery review for that new ID, and explicit recovery commit. Nothing auto-recovers.
Refresh/re-browse and prepare a fresh review before another action.
There is no hard total filesystem deadline. See
[the b3 backend contract](docs/architecture.md#m36b3-canonical-backend-restore-commit).
The [b4 GUI contract](docs/architecture.md#m36b4-explicit-gui-historical-restore)
is implemented and validated; live GUI behavior is not verified.
Separate renames are not pair-atomic; no reload IPC is sent, but watchers may
auto-reload changed files.

### Foreign-current scoped diagnostics (backend only)

`scoped_foreign.observe_current(config_root, state_root, selected_scope)` and
`revalidate_current(observation)` observe existing registered routes off GTK;
`run_observe(..., cancel_event=None, timeout=30)` supervises an isolated read-only
worker. The distinct frozen `ScopedForeignObservation` binds exact roots, registry,
protected context, selected raw UTF-8 text/hash/path proof/status, and the opposite
canonical v2 sibling's text, scope, content ID and counts. The selected raw text has
no canonical content ID or counts and never becomes `InstallationEvidence`.

Each scope is limited to 1 MiB, selected text to 10,000 lines, metadata to 1 MiB,
and total ASCII-escaped transport to 8 MiB with JSON depth 24. Strict UTF-8/control
checks preserve exact admitted bytes, including CRLF and final-newline presence.
Canonical selected v2 (either scope), canonical v1, and detected unknown record
versions refuse. After canonical parse failure, all recognized record-header lines
are checked independently of whole-file prefix, tolerating leading BOM U+FEFF and
ASCII space/tab for detection only. Unknown header versions and known headers with
embedded JSON integer versions outside v1/v2 refuse without changing raw text or
ownership classification. Damaged exact-marker text is `invalid-scoped`, other admitted text
is `foreign`. Existing ownership, permissions, Stow, alias/protected-path and Git
policies still apply. Canonical inspection still requires both canonical scopes.

Transaction contents are **UNASSESSED**, never scanned/read. An initialized store
is not required; pending/corrupt journals do not by themselves prevent diagnostics.
This is not write authority, a pending-conflict check, or a protection bypass.
B5 adds no preservation storage, source/candidate selection, proposal, diff, commit,
GUI activation, provisioning, main Lua read, compiler invocation, or IPC. Existing
b4 canonical historical restore remains available. See
[the b5 contract](docs/architecture.md#m36b5-foreign-current-diagnostic-observer).

### Legacy output contract

In legacy mode, the GUI's fixed default output is `$XDG_CONFIG_HOME/hypr/attune.lua`, falling back
to `~/.config/hypr/attune.lua`. Settings does not offer path editing.

- Only a dedicated `attune.lua` is writable; the resolved destination must also
  be named `attune.lua`, never the main configuration.
- Empty provisioned files are supported. Nonempty files must have Attune's
  canonical `-- Generated by Attune` header, base64 JSON data record, and exact
  generated Lua body. Reading reconstructs the data without executing Lua.
- Manual changes to the generated file, including added comments, are refused.
  Keep hand-authored Lua elsewhere; do not add it to this file.
- Existing file and parent-directory symlinks are preserved by writing the
  resolved destination. Dangling/cyclic links, hardlinked targets, and non-regular
  files are refused. The parent directory must already exist.
- Previous nonempty canonical content is backed up under
  `$XDG_STATE_HOME/attune/backups` (default `~/.local/state/attune/backups`) as
  `<sha256-of-previous-bytes>.lua`. Backups must stay outside Git working trees;
  a new or empty file has no previous-content backup.

## Data Flow

1. Startup inspects editor entry off GTK: `legacy-clear` reads v1 managed data;
   `pair-ready` supplies canonical pair models; blocked/error results open recovery.
   No main Lua parsing, provisioning, or compositor reload occurs.
2. Appearance/display interactive edits can immediately change compositor state via IPC, without
   writing any config file. Undo/discard operate on captured session baselines.
3. **Ctrl+S opens Pending Changes**, not a disk write. Review the exact diff,
   including previously managed values that will be emitted.
4. Choose **Save Reviewed Appearance / Displays**. Legacy save rechecks the draft, saved bytes,
   and resolved destination, validates ownership and Lua syntax, backs up previous
   nonempty content, and atomically replaces the resolved file.
5. Pair Save uses journaled group publication and fresh exact post-save verification
   before updating baselines. Only verified success enables continued editing.
   Persistent loading remains an explicit configuration decision described below.
6. Keybindings remain local drafts throughout editing. Their independent review
    and **Save Reviewed Keybindings** action write only the dedicated bindings file.
    Persistence does not prove runtime loading; watchers may auto-reload watched files.
7. Existing source shortcuts use explicitly selected TSV metadata, not that generated
   bindings file. **Save Reviewed Source Shortcuts** has its own complete review,
   backup and verified baseline; it preserves the other units' dirty/undo state and
    does not activate the offline main/bridge/data candidate.
8. Devices and Cursor share Input's owned baseline and optional read-only runtime hints.
   Local edits enter one complete combined review; **Save Reviewed Input** publishes
   and verifies only that output. Saving any of the four units preserves the other
   units' drafts, saved baselines and undo history. There is no Save Everything.

## Edge Cases

- **Live preview is not persistence.** Unsaved appearance/display edits can still alter the desktop.
  Saving does not itself force a compositor reload; do not equate the saved file
  with the current runtime state.
- **Removing a visual override:** the preview uses the schema default, not your
  hand-authored fallback for scalar options. Animation and monitor removals leave
  the current live state alone. After saving the removal, explicitly reload your own
  Hyprland configuration to restore the authored baseline. Reloading can also
  discard other unsaved IPC changes and run reload-time configuration behavior.
- Keep or revert a pending monitor preview before leaving the monitor page or
  saving. Closure, including SIGINT/SIGTERM, is held until that preview is resolved
  so its rollback timer can finish. Accepting a preview is not a disk save.
- **Save Preset** writes the curve library under `$XDG_CONFIG_HOME/attune`
  immediately. Applying those points to compositor configuration is a separate
  pending change requiring review. Undo/discard restores the compositor draft,
  not the separately saved preset library.
- A changed draft invalidates review; prepare a fresh review before Save. Legacy v1
  also requires a fresh review after disk/destination changes, subject to ownership
  checks. An existing-pair session cannot adopt externally changed files/routes:
  manually correct or restore the registered canonical files/routes, then restart/
  reopen Attune. Retry review only for temporary failures. Retained edits are
  session-local and do not survive restart.
- Lua validation is **compile-only** (`luac -p`, or `lua -E` with `load`). It does
  not execute the generated chunk and is not full Hyprland semantic validation.
  A missing validator, syntax failure, or backup failure prevents replacement.
- Advisory locking and destination/content rechecks reduce accidental stale
  writes; they do not guarantee safety against hostile filesystem races.
- If ownership checks reject a file, preserve it and inspect it outside Attune.
  Do not strip the checks or paste hand-authored Lua into a generated file.

## Example usage

### First Input save, then optional manual loading

1. Open Devices or Cursor in an admitted legacy or pair editor. Check the runtime-hint/default
   label; opening alone must not create pending overrides. Edit a keyboard, mouse or
   touchpad or allowlisted Cursor value. There is **no input/cursor preview**,
   including during Undo/Reset/Discard.
2. Press Ctrl+S, inspect the full combined Devices/Cursor diff, hashes and
   lexical/resolved paths, then choose **Save Reviewed Input** if intended. This
   saves both views together; the other three units save separately.
3. Only after the file exists, manually add `dofile` with the **actual absolute path
   from review** to your own Lua entrypoint after your defaults. At this user's
   default location only:

   ```lua
   dofile("/home/jdawson/.config/hypr/attune-input.lua")
   ```

   Use the actual path if XDG_CONFIG_HOME differs, not a literal shell variable.
   Attune makes no loader edit and sends no reload. Future live loading/checking
   requires separate explicit permission. An already watched file may auto-reload;
   saving does not prove loading or input behavior.
4. Make another edit/review/Save, then reopen to inspect persisted overrides. These
   are acceptance instructions, not a report of passing tests or live execution.

### Inspect installed existing shortcuts or preview prepared mappings

1. Close/reopen Attune and open Keybindings -> Existing shortcuts. Confirm the
   installed default path. To preview the separate checkout TSV instead, choose
   **Open Prepared Source Mappings** and confirm the reference path.
2. Search for an ID such as `terminal.return`, edit its key or description, and
   choose Update Pending. The authored action is unchanged.
3. Choose **Review Source Shortcuts...** here or from Pending Changes, inspect the
   complete diff and paths, then **Save Reviewed Source Shortcuts** if desired.
   Save additional bindings and visual changes separately. This is source metadata
   persistence, not installation or proof of runtime loading.
4. To clear Super+T, close/reopen Attune, confirm the **installed default TSV**
   (not Prepared), find Open terminal (T) / `terminal.t`, click its pencil, clear
   **Shortcut**, choose **Update Pending**, **Review Source Shortcuts...**, then
   **Save Reviewed Source Shortcuts**. No deployment is needed. The user performs these
   actions, not an agent on their behalf. Ctrl+S/visual Save alone is not source Save.
   All 80 rows stay in order; this row's shortcut stays blank after Save/restart and
   its edit dialog opens empty. Disable is a separate key-retaining choice. Changes become effective on
   the next configuration load, not automatic IPC; watcher reload is unproven and may
   happen immediately. Reload Hyprland configuration if needed; any manual command is
   the user's deliberate choice and can reset unsaved live previews. No reload was sent.

### First managed-keybindings save, then manual loading

1. Open Keybindings in an admitted legacy or pair editor. Add an unused supported
   shortcut, using Manual Edit if GTK recording cannot receive it. Inspect runtime
   overlap warnings or the unknown-inventory notice. This changes only the draft.
2. Press Ctrl+S, inspect the complete keybindings diff and actual absolute output
   path, then choose **Save Reviewed Keybindings**. Appearance/displays save separately.
3. **Only after the generated file exists**, manually add `dofile` for the exact
   absolute lexical path shown in review to your own Lua entrypoint. For this user's
   default XDG location, the example is:

   ```lua
   dofile("/home/jdawson/.config/hypr/attune-bindings.lua")
   ```

   If XDG_CONFIG_HOME differs, use the actual absolute path from review, not this
   example or a literal `$XDG_CONFIG_HOME` expression. Attune inserts no includes
   and requests no reload. Any deliberate live loading requires separate permission;
   saved does not mean loaded, and watcher behavior is not established here.
4. Reopen to inspect persisted owned rows. Deleting one removes its generated
   directive on the next bindings Save; it does not unbind a runtime shortcut.

These are instructions, not a report of executed or live-validated behavior.

### Edit an existing registered pair

Launch with the existing registry, canonical scopes, and safe initialized store.
Change an appearance value, press Ctrl+S, inspect **both** scope reviews (displays
should be unchanged), then choose **Save Reviewed Appearance / Displays**. After verified success,
make another edit and repeat Save, then reopen to inspect persisted values. This is
the implemented and validated workflow, not authorization to run it on live state.
No provisioning or loader change is part of this example.

### Legacy first reviewed save, then manual integration

1. Launch from the checkout, adjust a supported visual option, press Ctrl+S,
   inspect the diff, and select **Save Reviewed Appearance / Displays**.
2. Only after the file exists, explicitly add the following to your own Hyprland
   Lua entrypoint, at the end or after the appearance/monitor defaults it should
   override:

   ```lua
   require("attune")
   ```

   This example assumes the Hyprland config directory is on the Lua module path
   and resolves `attune` to the dedicated file. Match your configuration's module
   path and auto-reload setup; do not assume `require` will find an arbitrary
   symlink target. The UI guidance also permits `dofile` with the absolute path
   to the managed file when that better matches your configuration.
3. Deliberately reload and check Hyprland's behavior/errors. Ensure future saves
   are loaded by your chosen reload setup; atomic writes and module loading are
   not a promise of automatic reload.

These legacy-loading instructions are not an execution report. The separate source
integration deployment above does not establish live visual UI acceptance.
Isolated GTK smoke tests cover startup, page
navigation, edit/review/save/reopen, and foreign-file recovery with compositor
IPC disabled. Live monitor/HDR and animation preview still need manual acceptance.

### Optional dotfiles / Stow ownership

You may explicitly provision a dedicated source file named `attune.lua` in your
dotfiles and use Stow to expose it at the default config path. An empty source
file is supported for the first save. Provision the source before creating the
link: dangling targets are refused. Review/save will update the resolved source
file while preserving the symlink, so inspect that dotfiles change yourself.
Keep state backups outside the repository. Stow setup and adding the Lua load
line are separate user opt-ins, never automatic Attune setup steps.

## Related files

- `hyprmod/core/input.py`, `hyprmod/pages/input.py`: typed Input codec, local drafts
  and independent reviewed Save. `hyprmod/core/owned_output.py` shares fixed-output
  safety mechanics with bindings, not a generic plugin or visual-scope framework.
- `hyprmod/core/source_bindings.py`, `hyprmod/pages/source_bindings.py`: explicit
  source metadata observation, drafting, complete review and independent Save.
- [Offline integration bundle](integrations/hyprland/jdawson/README.md): candidate
  main, trusted bridge, stable-ID TSV and isolated registration-equivalence contract.
- `hyprmod/core/bindings.py`, `hyprmod/pages/managed_bindings.py`,
  `hyprmod/binds/dialog.py`: dedicated bindings codec/writer, local draft page,
  and GTK-only recording/dialog. See the [bindings contract](docs/architecture.md#managed-keybindings).
- [ADR 0001](docs/decisions/0001-shared-local-ownership.md): ownership and transaction
  decisions, existing-pair editing, and separate future migration design.
- `hyprmod/core/editor_layout.py`, `tests/test_editor_layout.py`,
  `tests/test_pair_editor_gui.py`: editor entry, pair review, and repeated-Save coverage.
- `hyprmod/core/transaction_publication.py`: explicit split writer and
  reviewed recovery backend, also used by explicit GUI historical restore.
- `hyprmod/core/scoped_recovery.py`, `hyprmod/core/layout_guard.py`,
  `hyprmod/pages/scope_recovery.py`: startup assessment, v1 exclusion, and explicit
  transaction recovery and separate reviewed canonical historical restore.
- `hyprmod/core/scoped_restore.py`: read-only historical listings/drafts and explicit
  canonical restore commits used by the GUI, not foreign-current recovery.
- `hyprmod/core/scoped_foreign.py`: backend-only foreign-current diagnostics,
  distinct from canonical installation evidence and preservation/write authority.
- [ROADMAP.md](ROADMAP.md): priorities, milestones, and acceptance criteria.
- [CONTRIBUTING.md](CONTRIBUTING.md): development commands and verification policy.
- [docs/architecture.md](docs/architecture.md): current interfaces and persistence boundary.
- [docs/validation.md](docs/validation.md): verification evidence and outstanding live acceptance.
- `hyprmod/core/focused_ui.py`: supported pages/options and review snapshot type.
- `hyprmod/core/persistence.py`: canonical reader, validation, backups, atomic save.
- `hyprmod/window.py`, `hyprmod/pages/pending.py`: review and save orchestration.
- `hyprmod/main.py`: public entrypoint; internal module names are retained.
