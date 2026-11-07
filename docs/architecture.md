# Attune architecture

## Overview

Attune is the focused appearance/monitor, input and managed-keybindings fork of
BlueManCZ/hyprmod at `b475087`.
The public executable is `attune`; the Python package remains `hyprmod`.
Upstream attribution and GPL-3.0-or-later licensing are retained in [LICENSE](../LICENSE).

The supported GUI is constrained before page construction, state registration,
and search indexing. It exposes general visual options (gaps, border size/colors),
decoration, animations/beziers, monitors, Devices, Cursor, managed Keybindings, Pending Changes,
and read-only Settings.
Health is an independent read-only utility, also available from startup recovery.
Backup inspection is another independent read-only utility. Its separate disk
restoration workflow participates in the editor exclusion gate, not ordinary
dirty/undo contributions or live preview.
Inherited profile, general binding/override, rule, workspace, autostart, environment, plugin, and
generic configuration helpers are not the focused application's feature contract.
Authored callbacks and live bindings remain untouched by normal editing. A narrow
user-approved offline integration candidate separates declarations/labels from Lua
actions; the app edits only selected TSV metadata, never main Lua. The dedicated bindings workflow below
does not establish the provenance of any runtime entry.

The editor supports unchanged `legacy-clear` v1 behavior and an existing registered
canonical v2 pair. **Pair editing/review/Save/continue is implemented and validated.**
Startup/Save create no registry, initialize no store,
provision no absent/empty visual-scope targets, migrate no data, and select no runtime loader.
Bindings and Input have their own absent/empty target contracts, independent of visual scopes.
[ADR 0001](decisions/0001-shared-local-ownership.md) records ownership and separate
future migration design. Automatic scoped foreign preservation is deferred and
nonblocking for canonical editing or canonical-only migration.

The current pair path below supersedes earlier checkpoint descriptions of inactive
editor routing. Legacy APIs apply only to `legacy-clear`; the M3 sections retain
supporting contracts, not a requirement to finish every foreign-recovery edge case.

## API / Interfaces

### Bluetooth manager handoff

`BluetoothPage` is an independent utility under Devices in both normal editor
layouts. Only **Open Bluetooth Manager** resolves `blueman-manager` on PATH and
starts it with a fixed argument vector through `Gio.Subprocess`, without a shell
or waiting for exit. Opening/navigating the page has no external effects. The
manager owns its separate window and lifetime; closing Attune does not stop it.
Missing-executable guidance and immediate spawn errors are visible and retryable.
Spawn success is labeled as a launch request, not proof of a visible window,
working BlueZ service, pairing or connection.

The launcher has no config model, dirty state, undo, output or writer ownership.
Editor uncertainty does not disable it. Blueman handles live device actions and
authorization; Attune does not install packages, control services, access BlueZ,
embed Blueman or add Bluetooth operations to Pending Changes/Save Reviewed Input.

### Existing source shortcuts

#### Overview

**Current UI correction, implemented and validated:** all 80 rows
stay in one stable **Keybindings** list. Every pencil opens **Edit Source Shortcut**;
no Delete button, Assign New action or Unassigned expander. Clear **Shortcut**, choose
**Update Pending**, **Review Source Shortcuts...**, then **Save Reviewed Source Shortcuts**.
The same row stays blank after Save/restart and its dialog opens empty. Pending says
**Clear shortcut** (Removed). Backend/state/schema and installed bridge capabilities
are unchanged; no deployment is needed. Entering a key from blank defaults Enabled on.
Final full pytest **4,361 passed, 383 skipped**; six isolated Broadway suites **380
passed, 2 skipped**. See [current validation](validation.md#ui-only-correction-final-validation).
Earlier counts below predate this correction; live behavior remains unverified.

The original key/description workflow has an automated/isolated GTK checkpoint.
True Delete/unassignment is **implemented and validated in code and isolated tests**.
The user-approved Delete-capable bridge-only deployment completed on 2026-11-03 UTC.
Installed `1d1023aa...` supports both capabilities, preserving main Lua and mappings.
Installed-default pencil/clear/Update Pending/Review Source/Save Source needs no
deployment; runtime unassignment behavior remains unverified.
The earlier reversible disable fix is implemented and validated in code through automated
and isolated GTK checks. The user-approved compatible bridge-only update is installed,
preserving main Lua and TSV; runtime disable behavior remains unverified. Keybindings has
**Existing shortcuts** (`SourceBindingsPage`) and **Additional bindings**
(`ManagedBindingsPage`) tabs. The pre-deployment live inventory contained 80 `__lua`
entries and zero descriptions. A numeric runtime `arg` is a Lua registry reference,
not source text or a line number. The runtime list prefers supplied descriptions,
but none were present then. Approved deployment on 2026-11-02 yielded 80 exact
catalog descriptions, unchanged keys/flags/native contexts and zero config errors
in read-only inspection. Live shortcut behavior remains user-untested.
No authored main is evaluated by Attune to infer actions.

The owner-approved refactor remains under `integrations/hyprland/jdawson` as a
reference main, bridge and stable-ID 80-row TSV. Reviewed copies were separately
deployed into the actual Stow source, preserving the config-root symlink; the project
directory is not directly loaded. Callback bodies and definition sites remain unchanged;
registration now supplies descriptions. Normal app Save never rewrites main Lua or unbinds runtime
shortcuts. Existing managed Lua formats and visual journals are unchanged.

#### API / Interfaces

| Interface | Role |
| --- | --- |
| `SourceBinding` / `SourceConfig` | Frozen rows: `id`, descriptive `context`, native `submap`, sorted `flags`, `key`, `description`; `assigned` means nonempty key, `enabled` means assigned and not `disabled`. Exactly empty key without `disabled` is unassigned; empty plus `disabled` is invalid. Catalog `jdawson.hyprland`, 1-1,000 rows, unique IDs and normalized enabled combos per native submap. |
| `read_text` / `build_text` | Six-column TSV with exact version/catalog/schema header and final LF, at most 256 KiB; no Lua evaluation. Keys at most 256 characters, descriptions at most 512, no controls. |
| `SourceBaseline` / `observe` / `run_observe` | Existing explicit lexical/resolved `keybindings.tsv`, exact text/config/hash, selected `PathProof`, actual `config_root`, immutable protected proofs and metadata-only `installed_route: PathProof` for that root's `hypr/keybindings.tsv`; strict JSON transport validates these fields. Observation APIs accept optional keyword `config_root` (XDG/home default), supervised read defaults to 15 seconds. |
| `SourceReview` / `prepare_review` / `run_prepare_review` | Fresh complete CURRENT -> GOAL diff, exact reviewed baseline/proposal and derived review hash; narrow `same_source` permits only safe sibling-leaf refresh for a new review, keeping own source/Git and installed route strict. Immutable metadata/order comparison; supervised read defaults to 30 seconds. |
| `SourceSaveResult` / `persist_reviewed` | Direct non-daemon writer: `saved`, `no-op`, `failed`; verified baseline on success, backup path and sticky `may_have_written` flag. No compiler or IPC. |
| `SourceBindingsPage` | Explicit file selection/prepared shortcut, key/description/assignment/enabled drafts, blank-field clearing, separate Disable/Enable and dialog Enabled switch, unified stable Keybindings list with a pencil for every row, search, SavedList baselines/undo, review, one-use Save and exact baseline adoption. |
| `window` / `PendingChangesPage` | Existing/additional tabs, pending source review and explicit Additional bindings row navigation, `source-bindings` writer owner, close veto, monitor-preview gate and independent undo cleanup. |

| State / action | Stored key | `disabled` | Persistence and Pending |
| --- | --- | --- | --- |
| Enabled | Nonempty | Absent | Assigned and enabled |
| Disable | Nonempty key retained, off | Present | Assigned and disabled after normal restart; Modified |
| Clear Shortcut field | Exactly empty; old key value removed entirely | Absent | Same row blank after restart; Clear shortcut (Removed) |

Persistence assumes valid saved data and a compatible bridge. The retained action
definition is not an assigned binding: its row stays in place with a blank shortcut;
the same pencil opens an empty field, never an automatically restored old/default key.

#### Data Flow

1. Initial observation targets `$XDG_CONFIG_HOME/hypr/keybindings.tsv` with the usual
   `~/.config` fallback. Open Prepared Source Mappings explicitly selects the checkout
   TSV; Open Source Mappings selects another existing file. Neither copies, provisions
   nor installs data. The admitted visual startup gate still applies. The GUI passes
   actual config-root context explicitly; observe/review worker requests and responses
   bind source path, state root and config root, including required `--config-root`.
2. Edit only key/description/enabled state. Preserve catalog, IDs, context, submap,
   base flags and order against the loaded baseline. Search and Pending Changes use
   metadata, not callback parsing. Dirty source edits must be discarded before choosing another source.
     A blank dialog field clears the key and removes `disabled`, preserving
     base flags and the catalog record. Pending Clear shortcut is Removed, assignment Added,
    Disable/Enable Modified. Undo/Redo, Discard and per-entry Revert preserve enabled,
    disabled and unassigned states. No catalog row or authored action is deleted.
     The summary counts total keybindings, shortcut fields set and disabled assignments.
     All rows remain in catalog order in one list; search filters visibility only.
3. Review reobserves exact bytes/routes and renders the full diff with lexical/resolved
   paths and hashes. Further edits invalidate review. Transport is bounded to 16 MiB;
   diff to twice the 256 KiB input bound plus 65,536 bytes. Oversize refuses.
    If any proposed row is disabled or unassigned, review and writer rechecks require the selected
   TSV's companion `keybindings-bridge.lua` to match a captured protected path proof
   and start with `-- Attune source bindings capabilities: disabled-v1` plus LF.
    Any unassigned row additionally requires the exact second line
    `-- Attune source bindings capabilities: unassigned-v1` plus LF, even if no rows
    are disabled. Only capability headers are read, never authored main Lua.
    Old/missing or disable-only helpers refuse unassignment with
    "Update the source keybindings bridge before saving disabled or unassigned shortcuts
    (requires disabled-v1 and unassigned-v1); older bridges would restore defaults."
    Disabled-only proposals require only `disabled-v1`. Direct commits cannot bypass
    this gate; metadata/route binding remains unchanged.
   If the selected and installed TSV share a resolved target or device/inode, both
   selected and actual installed companions must pass the capability/proof checks.
   A direct Stow/source path beside a new helper cannot bypass an old installed helper.
4. Save acquires window exclusion and calls the writer directly on a non-daemon worker.
   The dedicated state is `$XDG_STATE_HOME/attune/source-bindings.lock` and
   `source-bindings-backups/<sha256-of-prior-bytes>.tsv`. Private directories are
   `0700`, lock/backups `0600`, outside Git. Source may be in Git. Under the five-second
   advisory lock wait, recheck route/bytes/state, verify and synchronize prior-byte
   backup, then replace only the resolved TSV while preserving safe Stow links.
   Installed TSV route and both required helper proofs are bound and rechecked before
   state creation, under lock and immediately before replacement, including direct
   writer calls that bypass GUI review preparation.
5. Reobserve exact proposed bytes/config and unchanged route dependencies before
   adopting the baseline. Success clears only source undo. Failures retain drafts;
   possible publication or failed adoption locks only source. No-op can create lock/
   state but no backup/output. There is no hard total filesystem deadline.
   Post-write selected/installed route comparison allows only the writer's selected
   regular-leaf identity to change, including an aliased installed route; all other
   path/link/bridge facts stay bound. Unrelated offline TSVs remain independent.
6. The separately approved installation now supplies the runtime bridge and data.
   The app never executes authored main. At compositor load, the bridge validates all
   80 rows against its frozen catalog before any registration, or selects **all**
   defaults. It forwards original action objects unchanged and adds descriptions and
   original flags. Missing/unloadable bridge falls back to original source keys,
   callbacks and flags with descriptions. Trusted-source assertion failures are not
   a promise of fallback from arbitrary bridge implementation errors.
    In the candidate bridge, `register` consumes and checks every ID/context
    but skips `hl.bind` for disabled or unassigned rows. `finish` still requires all
    80 declarations seen, not 80 assigned/runtime bindings. The installed helper
    (`1d1023aa...`) supports both disabled and unassigned rows.
   `disabled` is metadata, never a Hyprland option. Installed-path observation and an
   separate in-memory-only Delete and Disable reviews pass without persistence. Current metadata does not
   prove the running process loaded the new helper; it may retain the old helper
   until the next configuration parse. All 80 TSV rows remain enabled.

#### Edge Cases

- The Python codec admits 1-1,000 rows; the trusted bridge requires exactly its 80
  catalog rows and metadata/order. App validation is not bridge activation proof.
- TSV has no quoting/escaping or callback column; tabs/newlines cannot be embedded
  in fields. No Lua evaluation or bridge JSON library is needed. Internal Python
  worker transport uses standard-library JSON, not an installed Lua JSON dependency.
- Duplicate normalized keys among enabled rows in the same native submap refuse.
  Disabled rows free their combination for another enabled source row. Conflicting
   re-enable (including pending Revert) refuses before mutation. All 80 declarations
   retain IDs, context, native submap, base flags, order, descriptions and authored
   callbacks. Disable retains the assigned key; Delete removes its old key value
   from the saved mapping, not an off tombstone. The page normalizes blank/whitespace-only
   dialog keys to exactly empty regardless of the Enabled switch. The codec accepts
   exactly empty keys without `disabled`, not whitespace-only keys or empty+disabled.
  The v1 header/schema and all-enabled bytes are unchanged. Old data works with old
  and new bridges, but an old bridge encountering `disabled` rejects the entire
   catalog and selects all 80 defaults. The prior disable-only helper likewise
   restores defaults for empty-key data. Capability checking therefore gates Save.
   Valid saved data with a compatible bridge preserves both disabled and unassigned
   states through Save/reopen and repeated configuration loads without resurrection.
   Missing/broken helpers or missing/invalid catalogs still use whole-default fallback;
   no unconditional no-resurrection guarantee applies under corruption.
   This is local metadata checking, not runtime conflict detection or full
   keysym/hardware alias validation.
  `manager` is descriptive Lua-state context with empty native submap; Wisp uses
  native `wisp`. Context alone cannot justify otherwise colliding keys.
- Row order is catalog presentation, not registration order. Candidate source sites
  retain registration order, including Wisp's unspecified `pairs` iteration.
- Missing/empty/foreign/malformed source is not created, imported or repaired. Both
  basenames must be `keybindings.tsv`, with an existing safe parent and owned,
  non-executable, single-link readable/writable file. Unsafe links/aliases and stale
   proofs refuse. Metadata-only protected proofs cover the actual config root's
  main/generated/registry routes (`hyprland.lua`, `hyprland.conf`, `attune.lua`,
    `attune-bindings.lua`, `attune-input.lua`, both visual scope files and `attune/installation.json`),
   plus `keybindings-bridge.lua`,
  independently of the selected source directory, plus equivalent source-sibling
  routes. Direct aliases and post-review route changes refuse. Authored Lua is never
  opened through these checks, including when the selected source is a Stow file.
- The candidate uses only `$HOME/.config/hypr` for bridge/data, not XDG discovery or
  a dotfiles fallback. Editing another selected TSV does not make that file loadable.
- Source, Input, additional managed bindings and visuals retain separate Save/dirty/undo
  units, never atomic Save Everything. Saved metadata does not prove loading.
  Saving an already-integrated or watched TSV may immediately auto-reload even
  without IPC; the GUI warning does not assume integration happens only later. Installation and
  rollback need explicit approval and outside-watched-path backups.
- Isolated 80-registration equivalence checks symbolic declarations and unchanged
   callback source/upvalues, not callback execution or live compositor behavior.
- The prior disable-only bridge cannot accept empty keys. Do not blindly downgrade
  after Delete and resurrect defaults. Require fresh compatibility review and user
  reassignment or a safe updated-helper plan. Older pre-disable bridges also reject
  disabled data. Never restore TSV snapshots over later edits.

#### Example usage

Close/reopen Attune -> Keybindings -> Existing shortcuts to observe the installed
default TSV (80 rows successfully observed). Edit a key/description, Review Source
Shortcuts, inspect the complete diff, then Save Reviewed Source Shortcuts only if
intended: saving watched data may immediately reload it. Additional bindings and
visuals save separately. Open Prepared Source Mappings instead selects the separate
reference TSV for preview; it is not needed to open the installed file. See
[deployment evidence and rollback safeguards](validation.md#source-integration-activation-and-rollback).
For true Super+T deletion, the user can now close/reopen Attune to load the new UI and
fresh bridge proof, confirm installed default TSV (not Prepared), find Open terminal (T) /
`terminal.t`, click its pencil, clear Shortcut, Update Pending, Review Source Shortcuts
and Save Reviewed Source Shortcuts. No deployment is needed. All 80 rows stay in order;
the same row remains blank after Save/restart and its pencil opens an empty field.
Ctrl+S/visual Save alone is not source Save. Do not perform deletion for the user.
Effects occur on configuration load, not automatic IPC; watcher reload is unproven
and may occur immediately. Reload configuration if needed; the user chooses any manual
command, which can reset unsaved live previews. No reload IPC was sent.

#### Related files

`core/source_bindings.py`, `pages/source_bindings.py`, `window.py`, `pages/pending.py`,
`core/ownership.py`, `core/undo.py`, `core/route_approval.py`, `core/persistence.py`,
`core/health.py`, and the [bundle README](../integrations/hyprland/jdawson/README.md).
Coverage source: `tests/test_source_bindings.py`, `tests/test_source_bindings_gui.py`,
`tests/test_source_bindings_equivalence.py`, `tests/fixtures/source-bindings-original.lua`.
Historical disable-only validation: full pytest **4,332 passed, 367 skipped**; all six
IPC-disabled Broadway suites **364 passed, 2 skipped**; backend/equivalence **304
passed**, source GUI **68 passed**. Full-tree Ruff/format, error-level Pyright,
wheel/candidate syntax/launcher help/diff checks passed; unfiltered GI warnings remain.
P1 direct-Stow/installed-helper regressions passed and independent source-only review
found no blockers. No live files/keys changed. See the
[current validation record](validation.md#source-shortcut-disable-fix-implemented-and-validated)
for timings, warnings, isolation and the later bridge-only deployment evidence.
Those checks were not rerun for that code-unchanged deployment and do not validate
the later unassignment fix. That historical pre-UI-correction checkpoint passed: full pytest **4,361 passed,
383 skipped**; six isolated Broadway suites **380 passed, 2 skipped**. Required
Ruff/format and error-level Pyright passed, not GI-warning clearance. Independent
review found no material findings. Mixed-state actual-disk Save/reopen and actual
Pending Delete/key reuse/conflicting Revert coverage is included. See
[final Delete validation](validation.md#source-shortcut-delete-versus-disable-implemented-and-validated)
for final HOME/XDG isolation, earlier non-prefixed run qualification, focused review
counts, warnings, timings, wheel/syntax/help/diff results and unchanged live hashes.
The Delete-capable helper is installed on disk; stable runtime metadata is not live
acceptance or proof of current-process helper loading. App code is unchanged and no
full suite was rerun for deployment. See the
[deployment record](validation.md#approved-delete-capable-bridge-only-deployment).

Historical results, predating disable support: full pytest 4,291 passed, 343 skipped; all six IPC-disabled
Broadway suites 340 passed, 2 skipped; focused equivalence 114 passed and source
backend 149 passed. Permanent key/description cases cover every one of the 80 IDs,
including virtual read-error/helper-syntax fallback regressions. Full-tree Ruff/
format, error-level Pyright, wheel/help/diff checks passed; independent rechecks
found no blockers. Timings, warnings, temporary-only publisher isolation and live
limitations are in [validation](validation.md#existing-source-shortcuts-current-evidence-and-limitations).
Historical managed-binding counts below retain their earlier checkpoint scope.

### Managed keybindings

#### Overview

**Implemented and validated** with automated and isolated GTK checks, not live
keyboard/loading acceptance. `ManagedBindingsPage` is the focused
Additional bindings tab of the `binds` page in both admitted legacy and pair editors, not the inherited override
editor. It owns only `$XDG_CONFIG_HOME/hypr/attune-bindings.lua` with the usual
`~/.config` fallback. No migration, split registry or new visual scope is required.
The existing startup admission gate still applies; this is not a bypass of blocked
visual startup. Profiles and layout pages remain outside supported scope.

#### API / Interfaces

| Interface | Role |
| --- | --- |
| `bindings.BindingsConfig(lines=())` | Frozen tuple of canonical directives, at most 1,000, unique normalized keyboard combinations, bounded to 1 MiB. |
| `validate_line` / `combo` | Exact parser round trip; normalize modifier aliases/order; admit only global keyboard `bind`, `binde`, `bindl`, `bindr`, `bindn` and library-renderable dispatchers/arguments. |
| `build_text` / `read_text` | Generated header plus distinct `-- Attune bindings data v1: ` base64 JSON record (`version`, `binds`) and exact library-rendered Lua body. Not visual v1/v2. No input Lua execution. |
| `BindingsBaseline` / `observe` / `run_observe` | Fixed lexical/resolved route, explicit roots, absent/empty/owned status, exact text/config and own/Git path proof, with separate explicit `protected` proofs. Read-only wrapper defaults to 15 seconds. |
| `BindingsReview` / `prepare_review` / `run_prepare_review` | Fresh baseline check and complete CURRENT -> GOAL diff, counts and fingerprint; read-only wrapper defaults to 30 seconds. |
| `BindingsSaveResult` / `persist_reviewed` | Direct non-daemon mutator; saved/no-op/failed, fresh adoptable baseline only on success, verified backup path if any, sticky `may_have_written` uncertainty. |
| `ManagedBindingsPage` | SavedList local drafts, search, pending rows, undo/discard, runtime observation, conservative combination checks, exact verified baseline adoption. |
| `BindEditDialog(..., draft_only=True)` | Add to Pending / Update Pending, keyboard-only validation, GTK event recording and Manual Edit fallback. No live mutation. |
| `PendingChangesPage` / `HyprModWindow.save_bindings_reviewed` | One-use exact review request, revision/context checks, direct protected writer lifetime, typed outcome validation and unit-local baseline/undo handling. |

#### Data Flow

1. First Keybindings visit asynchronously observes the dedicated file through the
   bounded read-only worker and queries `hypr.get_binds()` off GTK. Runtime inventory
   is a single snapshot, capped at 10,000 exact installed-client `Bind` objects.
   Offline/failed/empty results are unknown, not an empty verified conflict set.
2. Search matches shortcut/action/category/origin text. Add/edit/delete changes only
   owned local lines. `SavedList` and `SavedListSnapshot` retain per-row saved
   baselines, pending contributions and undo history. Unsupported dialog actions
   have no Edit button; owned rows can still be deleted. Runtime rows have no mutators.
   Draft-mode action lists hide submap. When a structured argument control would
   default or clamp the original value, the dialog falls back to exact plaintext,
   preserving arguments on shortcut-only edits.
3. Pending Changes prepares a complete bindings review separately from the visual
   review. Transport is bounded to 32 MiB, diff to 2 MiB + 65,536 bytes, generated
   text to 1 MiB. Edits/revision changes invalidate review; exact baseline/proposal
   and one-use request checks reject stale save delegation.
4. **Save Reviewed Keybindings** acquires the window's `save-bindings` owner, excludes
   overlapping writers, blocks editing during commit and vetoes close. Resolve any
   monitor confirmation first. The writer is called directly on a non-daemon thread,
   never a timeout-killable publication child. Its dedicated state is
   `$XDG_STATE_HOME/attune/bindings.lock` and
   `bindings-backups/<sha256-of-prior-bytes>.lua` (default state root `~/.local/state`).
   Private state directories are `0700`, lock/backups `0600`, outside Git. Existing
   empty prior bytes also receive a backup; absent priors do not. No pair journal,
   scope publication, visual store initialization or registry activation is involved.
   A `.git` directory or worktree file at the backup root itself is rejected before
   lock creation and rechecked under lock through final state verification.
5. Under the five-second advisory lock wait, reobserve exact source/route dependencies,
   compile-check generated Lua without executing it, verify/sync prior-byte backup,
   recheck before publication, and publish to the resolved target. Absent creation
   is exclusive; existing replacement preserves lexical Stow links. Fresh exact
   output, route and dependency verification must succeed before baseline adoption.
   No-op still validates/rechecks and may create lock/state, but no backup/output.
   Ten-second compiler checks do not bound total filesystem time.
6. Success adopts only the bindings baseline and clears only bindings undo entries.
   Visual Save skips bindings baseline updates and retains bindings undo history;
   bindings Save retains visual dirty state/history. There is no atomic Save Everything.
   Errors retain drafts; post-delegation invalid results, possible publication and
   failed adoption lock only bindings, not visual scope/journal state. Pre-delegation
   start failure adds no uncertainty. Owner release precedes fallible UI notification.

#### Edge Cases

- Every runtime row is external/read-only for authority purposes, including `__lua`
  opaque callbacks. Matching an owned combo does not prove origin or loading. No
  authored config parsing or `enrich_lua_binds` inference is used. Labels show
  descriptions, submaps, keycodes and true boolean flags **as reported by the installed
  client model**. A dedicated Lua flag is not supplied by that model; do not invent
  support or complete flag reconstruction. Read-only treatment is safe regardless.
- New/moved combos refuse any observed runtime overlap, even if its submap or flags
  might make it nonconflicting in practice. Same-combo edits of existing owned rows
  are allowed locally and warn on unknown-origin overlap. Owned duplicate combos
  always refuse. Offline inventory permits drafts with explicit uncertainty; neither
  a successful observation nor Save proves conflict freedom. No runtime refresh or
  conflict requery occurs during Save.
- Mouse, keycode/catchall triggers, submap dispatch, combined/other variants and
  control-bearing directives refuse. Recording sees only events reaching GTK;
  reserved shortcuts require Manual Edit, never compositor grabs or temporary unbinds.
- For `exec`/`execr`, validation uses public `dispatch_to_lua` to require an
  `exec_cmd`/`exec_raw` call whose decoded quoted argument equals the exact original.
  Library migration rewrites, including `hyprctl` arguments/instance controls, fail
  closed with guidance to use a direct action or Raw command only if intended.
  Actual Lua generation remains `keyword_to_lua`, not hand translation. Ordinary
  `$`, quotes, commas and operators are preserved when literal emission is proven.
  Tests inspect generated Lua bodies as well as metadata; this is not live execution
  or proof of compositor semantics.
- Owned-baseline Revert may restore the original saved combination despite opaque
  runtime overlap. Owned uniqueness is still checked before mutation; expected
  `ValueError`s are shown as toasts. No runtime override or unbind is involved.
- Exact plaintext argument fallback preserves values such as `dpms` argument
  `off HDMI-A-1`, `cyclenext` argument `prev`, and resize values of `20000` rather
  than silently defaulting or clamping structured controls.
- The resolved basename must remain `attune-bindings.lua`; its safe owned writable
  parent must already exist. Existing safe file/parent Stow links survive; dangling/
  cyclic links, hardlinks, unsafe files/parents, stale proofs, Git-unsafe state and
  aliases/collisions with main configs, legacy/scoped outputs, registry or state
  refuse. Protected routes are inspected as filesystem metadata, not opened as Lua.
- Foreign/manually changed/unknown-version nonempty output locks managed editing.
  Preserve and manually remediate it, then reopen. There is no import, auto-repair,
  bindings recovery browser, or automatic rollback. Failure can leave state/backup
  files; locks and checks are not protection against hostile filesystem races.
- No binding live-apply, override, unbind, reload IPC, include insertion or main-Lua
  read is added. Runtime IPC is observation only. Compile success is not compositor
  semantic validation. Persistence is not loading, and watched writes may auto-reload.

#### Example usage

Open Keybindings, add a supported unused shortcut to Pending, Ctrl+S, inspect exact
paths/hashes/diff, and choose **Save Reviewed Keybindings**. Save visual changes
separately. Only after generated output exists, manually add `dofile` with the actual
absolute lexical path shown in review to the user's Lua entrypoint. For the default
location on this checkout's machine, see the [README example](../README.md#first-managed-keybindings-save-then-manual-loading).
No loader edits or live verification were performed by this documentation pass.

#### Related files

`core/bindings.py`, `core/owned_output.py`, `core/route_approval.py`, `core/persistence.py`,
`core/ownership.py`, `core/undo.py`, `pages/managed_bindings.py`, `binds/dialog.py`,
`binds/live.py`, `window.py`, `pages/pending.py`, `core/focused_ui.py`, `ui/sidebar.py`.
Present test modules include `tests/test_bindings_persistence.py`,
`tests/test_managed_bindings.py`, `tests/test_managed_bindings_gui.py`, and
`tests/test_keybindings_workflow_gui.py`. Backend focus: 88 passed; full suite:
4,026 passed, 299 skipped; all five isolated Broadway suites: 296 passed, 2 skipped.
Required Ruff/format, error-level Pyright, wheel/help and diff checks passed.
See [validation](validation.md#managed-keybindings-implemented-and-validated) for
warnings, review fixes, isolation and the unexplained empty-file observation. No
live keyboard semantics or new mutator CLI is claimed.

### Devices / Input

#### Overview

**Historical Devices-only offline checkpoint, subsequently accepted by the user.**
Its final full pytest: **4,632 passed, 483 skipped**; eight isolated Broadway
suites: **480 passed, 2 skipped**. Required checks/build/help and parent diff check
passed; independent backend/UI review found no remaining material findings. See
[final evidence](validation.md#deviceinput-validated-offline-user-acceptance-pending)
for timings, warnings, isolation and the resolved P2s, not live-loading proof or
validation of the Cursor extension. Cursor is implemented, final validation pending.
`InputPage` exposes Keyboard, Mouse and Touchpad through Devices (`input` page ID)
in both admitted legacy and existing-pair editors. It uses its own immutable local
model, not `AppState` live mutation or visual v1/v2 storage. Startup admission stays
unchanged. No new `Scope`, registry entry or pair journal is added.

#### API / Interfaces

| Interface | Role |
| --- | --- |
| `OPTION_SPECS` / `normalize_value` | Closed 23-key type/range/choice contract: 15 Devices keys plus eight Cursor keys; finite numbers, exact booleans/integers, bounded XKB token syntax. |
| `InputConfig(values=())` / `from_mapping` | Frozen sorted unique key/value pairs, only explicit overrides. Variant requires layout; nonempty variant lists must align with layout slots. |
| `build_text` / `read_text` | Generated marker plus `-- Attune input data v1: ` base64 JSON (`version`, `values`), exact typed library-rendered Lua body, byte-exact regeneration required. No Lua evaluation. |
| `InputBaseline` / `observe` / `run_observe` | Explicit config/state roots, fixed lexical/resolved path, absent/empty/owned status, exact text/config/hash, immutable own/Git `PathProof` and separate explicit `protected` proofs. Read-only worker defaults to 15 seconds. |
| `InputReview` / `prepare_review` / `run_prepare_review` | Fresh baseline and complete CURRENT -> GOAL diff/counts/hash bound to exact proposal. Read-only worker defaults to 30 seconds. |
| `InputSaveResult` / `persist_reviewed` | Direct non-daemon writer, saved/no-op/failed, fresh adoptable baseline only on success, backup path and `may_have_written`. No publication child/CLI. |
| `InputPage` | Single owner of Devices and Cursor saved/current configs, labeled read-only hints, schema-backed rows, search/Pending, Reset/Discard and `_input_page` `SavedListSnapshot` undo, exact combined saved-baseline adoption. `build()` and `build_cursor()` return separate widgets, not separate models. |
| `PendingChangesPage` / `HyprModWindow.save_input_reviewed` | Complete bounded review, revision/context checks and one-use request; `save-input` owner, close veto, typed result validation and Input-local cleanup/locking. |
| `SettingsPage` | Read-only fixed output/manual integration and Git/Stow guidance. No output-path editing or loader insertion. |

All Devices keys below have the `input:` prefix. These 15 keys occupy 14 rows because
`kb_layout` and `kb_variant` share one editor.

| Section | Keys and validation |
| --- | --- |
| Keyboard | `kb_layout` + `kb_variant`: comma-separated XKB names/positional variants; `kb_options`: raw comma-separated XKB tags; `numlock_by_default`: boolean; `repeat_rate`: integer 0–200; `repeat_delay`: integer 0–2000. |
| Mouse | `sensitivity`: finite -1–1; `accel_profile`: empty/`flat`/`adaptive`; `left_handed`, `natural_scroll`: booleans; `scroll_factor`: 0.1–2.0 in 0.1 steps. |
| Touchpad | `touchpad:natural_scroll`, `touchpad:tap-to-click`, `touchpad:disable_while_typing`: booleans; `touchpad:scroll_factor`: 0.1–2.0 in 0.1 steps. |

Scroll limits are conservative, not an assertion that an unverified maximum of 10
is supported. `kb_options` preserves syntactically admitted unknown tags rather
than filtering through the XKB catalog. Strings are at most 1,024 characters and
XKB lists at most 32 tokens. Empty variant slots are positional; an empty variant
string is permitted with a managed layout. Layout cannot be empty when managed.

#### Data Flow

1. First visit to either Devices or Cursor observes owned output once off GTK using
   the shared bounded worker lifecycle. Optional
   `hypr.get_live` queries supply read-only hints; failures cannot replace a valid
   owned baseline. Owned/current values win, then valid runtime hints, then defaults.
   Unavailable/incomplete hints and defaults are labeled, not claimed as actual
   device state. Opening never creates overrides or output/state.
2. Edits replace only local `InputConfig`. Reset removes an override; Discard restores
   saved presence/value. Layout/variant edits, Reset and Discard act together with
   one undo snapshot. Pending may show both keys, but Undo remains one action.
   Undo/Redo, Pending Revert and whole-page Discard send no input IPC.
   Visible row origins distinguish **Saved override**, **Draft override**, **Current
   runtime snapshot** and **Default, not observed**. Unapplied `kb_options` entry text
   survives unrelated edits without bypassing Apply, and shows **Unapplied text
   (not in draft)** with its model origin. Only applied text enters the draft/review.
3. Ctrl+S renders Input separately from appearance/displays, source and additional
   bindings. The Input review combines Devices and Cursor, never a Cursor-only save.
   Review reobserves exact baseline/routes and includes full prior/proposed
   bytes, paths and hashes. Oversize refuses rather than truncating authority. Text
   is limited to 1 MiB, diff to 2 MiB + 65,536 bytes, transport to 32 MiB, JSON depth
   to 24. Edits in either view invalidate review; exact proposal/baseline, revision
   and one-use request checks precede save delegation. A new review may refresh only safe known
   sibling-output leaf evidence as detailed below; own source/Git stays exact.
4. **Save Reviewed Input** takes the global writer gate as `save-input`, excludes
   overlapping writers/editing and vetoes closure. Resolve monitor confirmation
   first. Publication runs directly on a non-daemon thread, never a timeout-killable
   child. Dedicated state is `$XDG_STATE_HOME/attune/input.lock` and
   `input-backups/<sha256-of-prior-bytes>.lua` (`~/.local/state` fallback), outside Git;
   directories are `0700`, lock/backups `0600`.
5. Under the dedicated advisory lock (five-second acquisition wait), recheck source,
   routes and protected dependencies, compile-check Lua without executing it, verify
   and synchronize prior-byte backup, then publish only to the resolved target.
   Existing empty priors also receive backups; absent creation is exclusive with no
   prior backup. No-op validates/rechecks and may create state/lock, but no backup/
   output. Ten-second compile checks do not bound total filesystem time.
6. Fresh exact post-save text/config/routes/dependencies must verify before baseline
   adoption. Success adopts the combined Devices/Cursor baseline and clears their
   shared Input undo; continued edit/review/Save and reopening
   use that verified baseline in either editor mode. All four save units preserve
   the others' drafts, saved baselines and undo, not atomic Save Everything. Errors
   retain drafts. Post-delegation uncertainty, invalid results or failed adoption
   lock both Devices and Cursor as one Input unit, not visual scope/journal state or
   other units. Inspect disk and reopen; no automatic recovery is offered.

#### Edge Cases

- Fixed output is `$XDG_CONFIG_HOME/hypr/attune-input.lua` (`~/.config` fallback).
  Resolved basename must match and the safe owned writable parent must already
  exist. Preserve safe existing file/parent Stow links. Reject dangling/cyclic links,
  hardlinks, unsafe files/parents and protected aliases. Main Lua, generated siblings,
  source TSV/bridge, registry and state routes are protected through metadata checks,
  not authored-Lua reads. Own-source or critical route/byte changes refuse; only a
  new review can refresh safe known sibling-leaf evidence, never a reviewed writer.
- Output may resolve to a Linux Git/Stow source, but remains a separate machine-side
  file, never shared appearance v2. The user decides what to commit; Attune never
  stages. State/backups must stay outside Git, including backup-root Git guards.
- Nonempty foreign, manually changed or unknown-format output blocks editing.
  No automatic import, overwrite exception, permission repair or rollback. Keep
  evidence and manually remediate/reopen. Failure can leave private state/backups.
- No live input preview, input mutation IPC, automatic loader/include insertion or
  reload. Save is not loading proof; an already integrated/watched file may reload
  automatically. Compile-only syntax/type emission checks do not prove Hyprland
  semantics, hardware effects or runtime option support.
- No profiles, window layouts, per-device hardware matching, global device-disable
  control or keymap-file editing. Touchpad disable-while-typing is not disabling the
  device; touchpad settings may have no effect without touchpad hardware.

#### Example usage

Devices or Cursor -> edit a local value -> Ctrl+S -> inspect the full combined
Devices/Cursor review -> **Save Reviewed Input**, saving both together. Only after
output exists, manually use `dofile` with the actual absolute lexical path shown
in review in the user's Lua entrypoint, after
defaults. See the [README example](../README.md#first-input-save-then-optional-manual-loading).
Future loading/live checks require explicit permission. The
[Devices-only offline checkpoint](validation.md#deviceinput-validated-offline-user-acceptance-pending)
is historical; [Cursor final validation is pending](validation.md#cursor-implemented-final-validation-pending).

#### Cursor: shared Input view

##### Overview

The user accepted the Input checkpoint ("so far so good"), then approved Cursor
work with "continue" after Cursor was proposed next. This authorizes the narrow
slice, not a claim of live Input loading or actual device verification. Cursor is
implemented, pending final validation. Rules/startup/environment are later slices.

##### API / Interfaces

`CURSOR_KEYS` selects eight of `INPUT_KEYS`' 23 closed keys. Cursor has eight widgets;
Devices retains 15 keys in 14 widgets. All Cursor keys use the `cursor:` prefix:

| Key | Type / range | Default |
| --- | --- | --- |
| `no_warps`, `persistent_warps` | Boolean | `false` |
| `warp_on_change_workspace` | Integer: 0 Disable, 1 Enable, 2 Force | `0` |
| `zoom_factor` | Finite float, 1–10 | `1.0` |
| `inactive_timeout` | Finite float, 0–20 seconds; 0 never hides | `0.0` |
| `hide_on_key_press`, `hide_on_tablet` | Boolean | `false` |
| `hide_on_touch` | Boolean | `true` |

Only zoom/timeout use `PreciseFloatOptionRow`, an `Adw.EntryRow` with explicit
Apply and locale-aware round-trip float display. It preserves loaded/typed float
precision without GTK spin rounding/epsilon or a one-decimal restriction. +/−
buttons use decimal arithmetic for 0.1 steps and apply the result. Existing
`SpinFloatOptionRow` behavior is unchanged; this is a small two-row widget, not a
generic framework. Backend normalization admits any finite in-range float with no
grid restriction, but `build_text` still requires public library typed-emission
proof: unrepresentable precision can refuse rather than be rewritten. No hand
emitter bypasses that proof. Types/defaults/ranges were checked against
`hyprland-schema` 0.7.1's bundled Hyprland v0.56.1 catalog and matching
[upstream ConfigValues.cpp](https://raw.githubusercontent.com/hyprwm/Hyprland/v0.56.1/src/config/values/ConfigValues.cpp).
This is version-specific source evidence, not support proof for every running version.

##### Data Flow

`window.py` constructs one `InputPage` and adds its `build()` and `build_cursor()`
widgets to separate stack pages. Both use the same baseline, local `InputConfig`,
read-only observation, revision notification and `_input_page` undo snapshots.
Search and Pending rows navigate to `input` or `cursor`; sidebar badges are
view-specific, while the shared dirty contribution is counted only once.

Typed numeric text is labeled unapplied and excluded from draft/review until Apply.
It survives unrelated edits and unrelated Undo/Redo. Whole-unit Discard and verified
saved-baseline adoption authoritatively refresh the entries from the shared model.

Opening either view creates no overrides. Saved/Draft overrides precede labeled
Runtime/Default hints, which do not prove actual cursor state. Edits, Reset,
Discard and Undo send no preview/mutation IPC. Per-row Discard restores that row;
whole-unit Input Discard restores Devices and Cursor together. Any edit in either
view invalidates the complete combined review. **Save Reviewed Input** publishes
both through the same `attune-input.lua`, `input.lock` and `input-backups`, then
adopts their verified shared baseline and clears shared undo. Uncertainty locks
both views as one unit. The other three units retain their draft/baseline/undo.

##### Edge Cases

Devices-only canonical bytes remain frozen and the input v1 record is unchanged.
Older Attune rejects newly admitted Cursor keys; unchanged version/old bytes do
not imply downgrade compatibility. There are still four save units, no fifth
output, new `Scope`, registry member or pair journal. Theme/size/environment,
`set_cursor`, GSettings, hardware and rendering controls are excluded; the inherited
`CursorPage` theme picker is inactive. Save does not insert a loader or reload;
watched writes may nevertheless reload. No live device/loading proof is claimed.

##### Example usage

Edit one Devices value and one Cursor value, open Pending, inspect the full shared
diff and choose **Save Reviewed Input** only if both changes are intended. There is
no save filtered to the visible page. Use temporary isolated fixtures for validation;
manual loading of an existing output needs separate explicit permission.

##### Related files

`core/input.py`, `pages/input.py`, `pages/pending.py`, `window.py`, `core/focused_ui.py`,
`ui/options/numeric.py`, `data/schema/options.json`; `tests/test_cursor_input.py`,
`tests/test_cursor_page_gui.py`, `tests/test_cursor_workflow_gui.py`, and the frozen
Devices-only codec fixture in `tests/test_input_persistence.py`. See
[pending checks and acceptance limits](validation.md#cursor-implemented-final-validation-pending).

#### Sequential independent saves: resolved P2 contract

Safe sequential Saves must not force unrelated drafts to be discarded or reopened.
Input and bindings baselines separate exact own-source/Git proof from explicit
`protected` proofs; Source retains its existing separate proofs and strict
`installed_route`. `same_source` in each of those three backends, using shared
`same_protection`, allows a **new review** to refresh only regular/absent leaf facts
for the known sibling outputs: `attune.lua`, the two visual scope files,
`attune-bindings.lua`, `attune-input.lua` and `keybindings.tsv`. Existing leaves must
remain safe owned single-link non-executable readable/writable regular files.
This is not permission to import sibling content or infer its runtime loading.

Own source bytes/config/proof and Git context remain exact. Protected lexical and
resolved paths, symlink targets, ancestor facts, main configs, bridge and registry
stay strict; Source's actual installed TSV route stays exact too. Unknown sibling
names and unsafe/nonregular leaf transitions have no refresh exception.

The freshly prepared review captures complete current evidence. Writers compare
that full reviewed baseline exactly under lock and through final checks before
publication, not `same_source` relaxation: **a post-review change invalidates Save**.
No silent rebase of an already reviewed Save is allowed. Normal post-save checking
still permits only the writer's own expected replaced regular leaf, with other
reviewed dependencies unchanged.

GUI completion/delegation retains the page's original baseline object identity,
proposal and revision checks, local draft and undo. It accepts a newly reviewed
sibling context only through narrow source matching, not by replacing that page's
saved baseline. Only its own verified save result is adopted; all other units'
drafts, saved baselines and undo survive. Historical Devices-only temporary real-publisher GUI
coverage passed **24 cases**, all **12 ordered unit pairs in legacy and pair modes**,
each saving all four units. Focused backend coverage passed **684 tests**. These
support the historical Devices-only full-suite/eight-suite results above, not
current Cursor validation.

#### Related files

`core/input.py`, `pages/input.py`, `core/owned_output.py`, `core/bindings.py`,
`core/route_approval.py`, `core/persistence.py`, `core/state.py`, `core/undo.py`,
`core/focused_ui.py`, `ui/options/keyboard.py`, `data/schema/options.json`,
`pages/pending.py`, `pages/settings.py`, `window.py`.
Coverage sources include `tests/test_input_persistence.py`, `tests/test_input_page.py`,
`tests/test_input_page_gui.py` and `tests/test_input_workflow_gui.py`. Final offline
evidence is linked above; earlier bindings/source/pair checkpoint counts are historical.

`owned_output.py` immediately shares only the concrete bindings/Input route, parent,
protected-name, lock, backup, compile, publication and verification mechanics for
two fixed kinds. Pending/window share their corresponding review/writer lifetime.
This is not a generic plugin/output registry. Each module keeps its own closed
codec, typed DTOs and review contract. Source TSV keeps its independent writer,
using relocated safety helpers, the added protected input basename and narrow
`same_source` matching for new reviews; its
stable 80-row list and blank-field unassignment guidance are unchanged. Visual
v1/v2 formats, `Scope`, registry and journals stay closed and unchanged.

### Existing canonical-pair editor

| Interface | Role |
| --- | --- |
| `editor_layout.EditorEntry` | Frozen explicit roots and `legacy-clear`, `pair-ready`, or `blocked`; only ready entries carry a pair, blocked entries carry a bounded reason. |
| `CanonicalPairLayout` | Exact `InstallationEvidence` plus immutable appearance/displays `ScopedConfig` models matching route bytes, IDs, and counts. |
| `inspect_entry` / `run_entry` | Read-only inspection; wrapper defaults to 30 seconds, exact root echo, strict 8 MiB transport. |
| `prepare_review` / `run_prepare_review` | Revalidate original pair, store and full pending scan before/after complete `GroupReviewPlan` construction; verify exact baseline and proposal goals. |
| `HyprModWindow.pair_proposals()` | Merge dirty scalar/section edits into saved local pair data; omit unchanged scopes. |
| `HyprModWindow.save_pair_reviewed(plan, proposals)` | Recheck review/editor/monitor gates, publish on a direct non-daemon worker, verify fresh post-save pair before adopting baseline. |

#### Data Flow

1. `main.py` supervises `run_entry` before window construction. Metadata-only
   `layout_guard.block_reason` admits unchanged v1 entry only for `legacy-clear`.
   Otherwise inspect the safe initialized store, scan all journals read-only, inspect
   explicit registered canonical routes, decode both models, then rescan/revalidate.
   A ready pair may have zero journals. Full scans verify terminal records and blobs
   within the 1,000-entry limit, not only the 32 recovery display rows. Old terminal
   actual-byte conflicts in `LayoutAssessment` are not readiness criteria.
2. A ready entry builds normal scalar, animation/Bezier, and monitor pages using
   local pair values/sections, without v1 `config.read_cached()` reads. Proposals
   merge only dirty values/sections, retaining untouched records, curves, animation
   definitions, and disconnected monitors rather than reconstructing them from IPC.
3. Pending Changes supervises read-only preparation off GTK, retaining one read slot
   through cancellation, and renders both precomputed CURRENT -> GOAL diffs with
   paths/hashes/content IDs. Inputs retain 256 KiB/10,000-line per-side limits;
   complete per-scope diffs retain 256 KiB/4,000-line limits. Oversize refuses.
   Edits/undo/reset invalidate review immediately; revision, pair identity and
   proposal checks reject stale completions.
4. Explicit Save consumes review, acquires the window's `save` owner, disables
   editing, and vetoes closure. It calls mature `publish_reviewed` directly on a
   non-daemon thread with explicit roots and no reused transaction ID. The writer
   rechecks under lock, compile-checks without executing Lua, journals, and stages
   changed scopes only. Owner exclusion prevents backup/recovery overlap.
5. Exact typed result validation precedes fresh supervised `run_entry` after
   committed/no-op success. Registry/context and route bindings must match, and both
   fresh texts must equal reviewed goals. Only then replace the local pair baseline
   and call `_perform_save` / `mark_saved`, clearing visual dirty/undo state while
   retaining bindings state/history and permitting
   repeated Saves without restart. This verified success path is distinct from
   recovery's old-editor invalidation.

#### Edge Cases

- Foreign/invalid/wrong-scope/missing outputs, absent/unsafe stores, pending/corrupt
  journals anywhere, scan limits, drift, and inspection errors fail closed. Reasons
  identify registry/routes/store and manual remediation, never overwrite or
  initialization. For pending work, explicitly refresh Scope Recovery, review an
  allowed action, then commit separately. For other damage, preserve originals and
  evidence, inspect externally, manually restore verified canonical scopes/safe
  store, then Retry Startup Check. Never delete evidence just to regain editing.
- Failures retain session-local dirty edits, which do not survive restart. Retry
  review for temporary failures only. External disk/route changes cannot be adopted
  into the original pair baseline: manually correct or restore the registered
  canonical files/routes, then restart/reopen Attune. Pending/uncertain
  outcomes, invalid delegated results, and post-save verification failure lock the
  editor without marking saved. Independent scope/journal flags remain sticky.
  Worker-start failure before delegation adds no uncertainty.
- Settings shows registered/resolved pair routes and labels Health/Backups as
  legacy-v1-only. Those utilities do not diagnose/restore this pair; canonical
  historical restore remains separate in Scope Recovery.
- No Save reload IPC, runtime-loading proof, pair-atomicity, or total filesystem
  deadline is promised. Watchers can auto-reload between renames. Lock/compiler
  operations retain their existing five-/ten-second bounds.
- `health.run_bounded(input_text=...)` supplies bounded UTF-8 stdin for large review
  requests rather than argv. Nonblocking input and stdout/stderr share the existing
  deadline, cancellation and process cleanup; oversized input refuses before launch.
  This is a small supervisor extension, not a new worker framework.

#### Example usage

For an already registered canonical pair and initialized store: launch, edit an
appearance value, Ctrl+S, inspect both scope diffs, Save Reviewed Appearance / Displays, then edit
and Save again. Reopen to inspect persisted data. No provisioning/loader handoff
is part of this sequence; live execution requires separate explicit confirmation.

#### Related files

`core/editor_layout.py`, `main.py`, `window.py`, `pages/pending.py`,
`pages/settings.py`, `core/health.py`; `tests/test_editor_layout.py`,
`tests/test_pair_editor_gui.py`, `tests/test_health_input.py`. Automated validation
passed; see [validation.md](validation.md#current-status). Live acceptance remains pending.

### Legacy and utility interfaces

| Interface | Role |
| --- | --- |
| `hyprmod.main:main` | `attune` entrypoint; rejects positional profile commands; desktop registration requires explicit flags. |
| `focused_ui.filter_schema(catalog)` | Keeps only general visual, decoration, and animation controls. `PAGE_IDS` also gates navigation. |
| `AppState` / `OptionState` | Tracks runtime/session baselines, managed ownership, dirty values, and IPC previews. |
| `ConfigSections` | Shared optional section buffers; focused persistence accepts only `monitors`, `animations`, and `beziers`. Unsupported fields must remain `None`; even empty lists are refused. |
| `ReviewSnapshot` | Frozen record of `path`, `saved_text`, `proposed_text`, and `resolved_path`; persistence requires a bound resolved path. |
| `HyprModWindow.review_snapshot()` | Resolves the destination, reads exact saved bytes as UTF-8, builds proposed canonical text, and rechecks destination identity. |
| `HyprModWindow.save()` | Opens Pending Changes only. Ctrl+S uses this review action. |
| `HyprModWindow.save_reviewed(snapshot)` | Requires Pending Changes, no unconfirmed monitor preview, and a matching fresh snapshot before persistence. |
| `persistence.build_text(values, sections)` | Validates supported scalar/directive shapes and emits canonical generated Lua plus data record. |
| `persistence.read_document(text)` | Reads empty or canonical Attune data without evaluating Lua; rejects foreign/manually edited content. |
| `persistence.resolve_target(path)` | Enforces a dedicated `attune.lua` destination and resolves file/parent symlinks. |
| `persistence.validate_lua(text)` | Compile-only syntax check, not Hyprland semantic validation. |
| `persistence.persist_reviewed(snapshot, values, sections)` | Revalidates review/ownership, backs up previous content, atomically replaces the resolved destination; returns a backup path or `None`. |
| `health.collect_snapshot(output_path)` | Collects seven read-only checks, sharing one secure owned-output read for ownership and drift, without constructing GTK widgets. |
| `health.run_snapshot(output_path, timeout=10, cancel_event=...)` | Supervises an isolated collector process, bounds captured output, and terminates its process group on completion, failure, timeout, or cancellation. |
| `HealthPage(output_path)` | Lazily requests one snapshot off the GTK thread, exposes explicit refresh, and retains stale results after a failed refresh. |
| `diagnostics.build_diagnostics_report(snapshot, stale=...)` | Projects observations into allowlisted report summaries, omitting raw details and identities. |
| `backups.run_list(output_path, cancel_event=...)` | Supervises bounded hash/canonical backup inspection and returns immutable listing metadata. |
| `backups.run_compare(output_path, name, cancel_event=...)` | Re-verifies a selected backup, inspects current output, and computes the bounded literal diff off GTK. |
| `ConfigDiffWidget.set_precomputed_diff(...)` | Renders already-bounded diff lines without computing a diff on the GTK thread. |
| `restoration.run_prepare(output_path, name, cancel_event=...)` | Read-only supervised validation produces an immutable, complete CURRENT -> BACKUP review draft. |
| `restoration.commit_restore(draft, cancel_event=...)` | Direct worker call revalidates and writes through the shared protected transaction, returning restored/unchanged or an explicit uncertain failure. |
| `recovery.run_prepare(output_path, name, cancel_event=...)` | Separate read-only worker binds foreign/invalid original text, canonical candidate, complete diff, and private preservation destination. |
| `recovery.commit_recovery(draft, cancel_event=...)` | Direct preservation-gated worker returns recovered output and preserved-original evidence; ordinary save paths have no foreign-content override. |
| `persistence.persist_snapshot(...)` | Shared canonical snapshot transaction with optional source guard and cancellable finite lock acquisition. |

`core/config.py` supplies the default
`$XDG_CONFIG_HOME/hypr/attune.lua` (`~/.config/hypr/attune.lua` fallback) and
managed-data caching. It still contains legacy generic helpers such as
`write_all`, path overrides, and format conversion. Those are not the GUI's
reviewed persistence API. Settings exposes neither path editing nor auto-save.

## M3.2 data foundations

These pure interfaces perform no filesystem operations, subprocess calls, Lua
evaluation, registry creation, discovery, or activation. Pair editing and explicit
recovery consume them; pure model construction grants no write authority.

| Interface | Role |
| --- | --- |
| `scopes.Scope`, `SCOPE_BASENAMES` | Shared immutable logical identities and dedicated appearance/display basenames. |
| `scoped_config.ScopedConfig(scope, payload)` | Validates a closed scope payload and copies its data into deeply immutable tuples. |
| `scoped_config.build_text(config)` | Renders canonical v2 metadata and Lua text in memory, not to disk. |
| `scoped_config.read_document(text, expected_scope=...)` | Strict, bounded v1/v2 decoding. V1 is a tagged full bundle, never implicitly one scope. |
| `scoped_config.partition_legacy(bundle)` | Explicit pure partition into both scopes, without approval to migrate or write. |
| `installation.parse_registry(text)` | Validates exact schema/layout/routes and normalized declared paths, returning immutable data and exact source-byte SHA256. |

Appearance payloads require exactly `values`, `beziers`, and `animations`; displays
require exactly `monitors`. Forbidden fields are rejected even when empty. Scalar
keys are sorted; directive order is preserved and duplicate directive identities
are rejected rather than silently collapsed.

V2 starts with the ownership header and `-- Attune data v2: ` record. Its compact,
sorted-key ASCII JSON contains exactly `version`, `scope`, `payload`, `content_id`.
The scope-local ID hashes canonical version/scope/payload data, while `byte_hash`
hashes the full emitted UTF-8 text. Bounded one-MiB decoding, duplicate-field/type
validation, expected-scope checking, identity recomputation, and byte-exact
regeneration reject edited or cross-scoped data without executing it.

The registry parser accepts at most 64 KiB, 16 JSON nesting levels, and 4,096 UTF-8
bytes per path. Exact input-byte identity changes when input whitespace changes;
`InstallationRegistry.to_json()` separately emits canonical schema-only JSON.
Declared path overlap, invalid basenames, non-normalized/relative paths, controls,
and interpolation are refused. Actual symlink resolution, file types, hardlink
aliases, permissions, protected targets, and outside-Git policy are **not** verified
by these pure declarations; the separate inspector below observes those facts
without granting write authority.

The v1 format remains unchanged, with public `build_document` for renderer reuse.
The v1 reader still rejects v2; M3.6a adds writer-side layout exclusion separately.
Literal combined/empty v1 fixtures lock historical emitted bytes and backup
validation. The models themselves activate no split cache, journal, runtime loader,
migration, or writer. Canonical validation is not live compositor acceptance.

## M3.3a route inspection foundation

`core/route_approval.py` is used by editor entry/review and explicit recovery. Its
public APIs require explicit normalized absolute `registry_path`, `config_root`,
and `state_root`; the registry must be at `config_root/attune/installation.json`.
Callers supply context; startup derives those roots from XDG defaults. There is no
filename-based activation or automatic provisioning.

- `inspect_installation(...)` directly observes an existing canonical v2 pair.
- `run_inspect(...)` performs the same read-only work in an isolated supervised
  child with a default ten-second deadline and cancellation.
- `revalidate(evidence)` / `run_revalidate(evidence)` recapture actual facts and
  reject an evidence-hash mismatch. New observation time does not change that hash.

Frozen, slotted evidence binds exact registry bytes, lexical/resolved paths,
symlink targets/identities, security metadata, scope content IDs/full-byte hashes,
canonical counts, protected context, and ancestor Git-marker facts. Directory
facts exclude timestamps/link counts so unrelated sibling activity is harmless.
File and symlink facts retain content/identity metadata. Full dependency rechecks
after both reads reject changing or mixed observations where detected.

Registry input must be user-owned, private `0600`, regular, and single-link. Both
outputs must be existing nonempty canonical v2 with the expected scope, user-owned,
regular/single-link, owner-readable/writable, non-executable, and not group/world
writable. Common `0600`/`0640`/`0644` output modes are accepted. Resolved immediate
parents must be owned, writable/searchable, and not group/world writable. No chmod
or repair is attempted. Missing/empty targets are provisioning states for future
migration, not a healthy ordinary installation.

Resolution captures file/parent links, bounds depth/hops, and confirms kernel-
followed lexical metadata agrees with the computed target. This matters for search
permissions and ACLs on directories later canceled by `..`; textual normalization
alone is insufficient. Protected main/legacy/registry/state collisions are checked
before reading potentially aliased bytes. Main files are metadata-only observations.
Registry and displays must resolve outside ancestor `.git` directory/file markers;
appearance may be inside Git. This is not discovery through arbitrary Git environment
variables or nonstandard configuration.

Limits are 64 KiB registry bytes, 1 MiB per output/evidence transport, 128 path
components, and 40 symlink hops. Direct calls have no hard filesystem-latency bound;
clients should use the supervised API off GTK. Serialized hashes are not authentication
or a durable permit. Inspection is transient and non-atomic; writers must
revalidate under lock and again before replacement, accounting for intentional state
provisioning rather than blindly ignoring changed evidence.

The layer never writes files, creates state, executes/compiles Lua, runs compositor
queries, or activates split routing. The adapters below consume its evidence;
the journaled writer is implemented below. Transaction recovery and separately
reviewed historical restore have GUI integration. Existing-pair Save uses the same
route checks; legacy Save remains subject to layout exclusion.

## M3.3b scoped adapters

These read-only APIs grant no write authority. Pair Save and explicit recovery
consume group reviews; backup/diagnostic adapters remain
separate from active legacy utilities:

| Interface | Role |
| --- | --- |
| `scoped_review.build_review(evidence, proposals)` | Freshly revalidates both routes, reads exact current canonical v2 text, and derives an immutable complete group proposal. |
| `scoped_review.revalidate_review(plan)` | Reconstructs candidate models and rederives all review semantics against current filesystem evidence. |
| `scoped_backups.describe_backup(name, text, expected_scope=...)` | Pure full-byte hash, canonical-format, and scope classification for supplied backup text. |
| `scoped_diagnostics.collect_scoped_diagnostics(evidence)` | Freshly revalidates the explicit installation and derives immutable per-scope identity/count observations. |
| `scoped_diagnostics.build_scoped_diagnostics_report(observation, stale=...)` | Pure fixed-summary projection, without rechecking freshness or exporting private identities. |

Group plans include both scopes in fixed order, registry/evidence identity,
lexical/resolved destination bindings, exact prior/proposed text, full-byte hashes,
scope content IDs, complete labeled diffs/counts, and a derived changed-scope set.
Proposals can omit a scope: its proposed text is the exact prior text, not a
runtime reconstruction or new generation stamp. No-ops produce no changed scopes.

Each side is bounded to 256 KiB/10,000 lines, and each complete diff to
256 KiB/4,000 lines. Oversized reviews refuse instead of truncating. Filesystem
evidence is revalidated before adapter reads and after both reads/diffs; every read
must match its observed byte hash. Review hashes exclude observation time but bind
all substantive fields. Revalidation rejects forged fields even with recomputed
fingerprints, because it reconstructs the plan from actual files and proposals.

Backup descriptors explicitly distinguish `legacy-full-bundle` v1 from `scoped-v2`.
An expected scope rejects v1 until explicit conversion, even if the bundle happens
to contain only appearance. V2 scope mismatches refuse. Counts are ordered as
values, Beziers, animations, monitors. Hash/canonical classification establishes
neither Lua syntax, semantic validity, runtime loading, nor restorability.

Diagnostic collection rejects stale evidence and records the fresh observation
time. Rendering a report does not revalidate it; stale export is explicitly labeled.
Only fixed text, known scope/version values, bounded counts, and normalized UTC
time appear in reports. Paths, hashes, usernames, ownership/inode metadata, raw
errors, registry contents, link targets, and scalar values are omitted.

No adapters write files, enumerate backup directories, compile/execute Lua, run
IPC, or grant write authority. Direct review/collection I/O and diff computation
must be supervised off GTK. M3.6a supervises recovery review preparation. The
separate private-evidence layer below implements storage for explicit publication.

## M3.4a transaction evidence foundation

`transaction_records.py` models only ordinary split saves whose two priors are
present-owned canonical v2. Absence and present-empty are distinct named kinds
but are refused by this first journal format, not collapsed into empty bytes.
Frozen/slotted snapshots bind the complete historical group review, both routes,
registry identity, exact texts/hashes/diffs/counts, and changed scopes. Intents
reference the content-addressed snapshot, review, registry, transaction ID, phase,
and fixed-order advisory progress prefix. JSON fields/depth/size/types and hashes
are strictly validated.

`scoped_review.validate_recorded_review(plan)` now validates historical structure
and exact complete semantics without filesystem freshness. This permits loading
evidence after a legitimate proposed-byte replacement. `revalidate_review(plan)`
still derives a fresh filesystem-backed plan and rejects drift. Neither function
compiles Lua or grants write authority.

`transaction_store.py` has explicit APIs, never startup/discovery hooks:

- `initialize_store(state_root)` provisions owned private directories and
  synchronizes their parent entries. It must precede route inspection/review.
- `inspect_store` / `revalidate_store` observe root identities, excluding unrelated
  directory timestamps. Preparation never silently initializes behind a review.
- `prepare_transaction(plan, state_root=...)` revalidates under the shared safe
  lock, verifies immutable prior/proposed blobs and snapshot, and publishes a
  prepared/empty-progress intent last. It does not replace either output.
- `load_transaction(state_root, id)` validates actual private records and every
  referenced blob, not current output state or publication authority.

The explicit store layout is:

```text
state_root/attune/
    blobs/<full-byte-sha256>.lua
    snapshots/<snapshot-sha256>.json
    transactions/<32-lowercase-hex-id>/
        intent.json
        rollback.json             # optional immutable reverse operation
        rollback-checkpoint.json  # optional reverse progress/completion
    persistence.lock
```

Legacy `backups/` and raw `preserved/` data remain separate. Private directories
require owned `0700`; files require owned single-link regular `0600`. State roots
and private paths reject unsafe ownership/modes, symlink components, and ancestor
Git markers. Existing permissions are never repaired. The state root itself must
already exist and be safe; initialization is an explicit API, not startup provisioning.

Evidence files are created exclusively, byte/hash/canonical verified, and
synchronized with containing directories before the prepared intent. Safe identical
immutable collisions may be reused; incompatible/unsafe collisions refuse. The
shared lock has a cancellable five-second acquisition bound. Unknown/incomplete
journal directories and unresolved predecessors block further preparation. No-op
preparation does fresh read-only validation and writes no blobs, intent, or lock.
Failures may leave partial/orphan evidence; no automatic repair or deletion occurs.

The current kind has an eight-MiB total evidence/record budget, JSON depth 24, and
1,000-entry journal-scan limit, plus existing per-scope input/diff bounds. Prepared
means private canonical evidence is complete, not that compile preflight or scope
publication has occurred. M3.4b separately performs those checks before replacement.

`transaction_inspection.classify_transaction(state_root, id, config_root=...)`
reloads the verified private bundle and inspects current scopes in explicit context.
It classifies changed scopes as prior/proposed/conflict and an untouched sibling
as unchanged only when its full evidence still matches. Safe changed-leaf atomic
replacement may change inode/timestamps; all registry, link-chain, parent, Git,
protected-context, and unchanged-sibling identities remain bound.

The overall result is all-prior, all-proposed, mixed, or conflict, based on actual
canonical hashes and content IDs rather than recorded phase/progress. Current and
private evidence are checked again before returning. Corrupt/missing evidence or
unexpected bytes/context return conflict, not permission to overwrite. No result
establishes an atomic snapshot, publication history, runtime loading, or recovery
authorization. This direct API has no worker, CLI, wall-time guarantee, or repair
actions; M3.6a supervises assessment off GTK.

M3.6a uses this layer to inspect existing evidence, never initialize it at startup.
Tests explicitly initialize temporary stores. The publisher below compiles and writes only when
explicitly invoked; no live store, registry activation, migration, or loader was installed.

## M3.4b publication and reviewed recovery backend

### Overview

`core/transaction_publication.py` implements the ordinary present-owned split-save
backend. Explicit mutator calls can replace scope files and private journals.
Existing-pair Save integrates ordinary publication and is implemented and validated.
No CLI mutation, registry creation/activation, initial provisioning, or migration
is added. Foreign preservation is deferred and does not block canonical-only
migration; M0 live rollout remains unverified.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `publish_reviewed(plan, *, state_root, config_root, transaction_id=None, cancel_event=None, expected_source=None)` | Requires explicit context matching a fresh complete `GroupReviewPlan`; prepares new evidence or explicitly selects the exact matching PREPARED transaction, then publishes changed scopes. Optional read-only source check runs under the writer lock. Generated ID collisions refuse, never select existing evidence. |
| `review_recovery(state_root, txid, action, *, config_root)` | Read-only preparation of a frozen `RecoveryReview` with the full CURRENT -> GOAL group plan and private fingerprint; actions are `resume`, `rollback`, `finalize`, `abandon`. Invalid/conflicting/terminal states raise errors. |
| `commit_recovery(review, *, cancel_event=None)` | Rederives the exact recovery review and private fingerprint under lock before the selected operation. Every attempt requires a fresh review. |
| `PublicationResult` | Frozen `transaction_id`, `outcome`, `pending`, independent `scope_may_have_changed` and `journal_may_have_changed`, plus optional `error`. Outcomes are `no-op`, `committed`, `aborted`, or `failed`. |

The two flags are conservative and sticky within an attempt, not inferred from
each other, outcome, or advisory progress. A journal-only change does not establish
a scope replacement; a failed rename/sync/checkpoint can still mean scopes changed.
Recovery callers **must invalidate editors on scope change or uncertainty**, never
mark old baselines Saved. Normal pair Save may adopt only its freshly verified
exact post-save baseline, not its old cached one. M3.6a also invalidates on independent journal uncertainty.
Mutators must run
directly on non-daemon workers, never in timeout-killable children. Lock acquisition
is cancellable with a five-second bound; each compile check has a ten-second bound.
There is no hard total deadline for filesystem work or an automatic worker wrapper.

### Data Flow

1. Explicitly initialize the private store before route inspection/review. Under
   the shared lock, revalidate the full review and reject other unresolved or
   malformed transactions. Prepare and verify private canonical evidence as needed.
2. Compile-check all current and desired scope texts before any scope replacement
   or staging. This never executes generated Lua and is not semantic validation.
   The sole exception is all-prior `abandon`, a metadata closure that deliberately
   skips compilation so failed/missing compiler preflight cannot trap an intent.
3. Synchronize private evidence; exclusively create owner-only `0600` staged files
   beside approved resolved targets **only for necessary changed scopes**. Flush
   and fsync every output stage before the first replacement.
4. Replace in fixed appearance-then-displays order. Recheck full expected
   intermediate group, registry, source/route/alias/protected context, private
   evidence, and stage identity/bytes immediately before each replacement. Fsync
   the output directory, inspect the resulting group, then atomically publish and
   directory-sync its private progress checkpoint. Repeat with updated expected facts.
5. Verify goal hashes/bindings, synchronize both outputs and their directories,
   and recheck before terminal recording. Reverse completion is recorded before
   parent ABORTED; forward completion records COMMITTED. A final route recheck
   follows the terminal checkpoint. Failures report uncertainty, not automatic rollback.

Lexical file/parent symlinks are preserved by replacing approved resolved leaves.
Untouched siblings and already-goal scopes receive no staging, replacement, chmod,
or mtime change. Reads and final fsyncs can affect atime. Publication no-ops replace
no scopes and create no transaction evidence, but the publisher enters the store
session and may create its lock file; this differs from read-only no-op preparation.

### Edge Cases

- Forward resume changes only original changed scopes still at prior bytes. It
  leaves already-proposed and unchanged inodes alone. Classification uses actual
  known prior/proposed states, even non-prefix mixtures, not recorded progress.
- All-proposed `finalize` is metadata-only with compile preflight. All-prior
  `abandon` is metadata-only and compiler-independent. Terminal transactions
  cannot be replayed as historical recovery operations.
- Rollback writes immutable `rollback.json` plus `rollback-checkpoint.json` in the
  original transaction directory, retaining schema-1 ordinary-intent compatibility.
  Its initial restore set includes only originally changed scopes actually at
  proposed bytes when rollback starts. Recording the operation locks direction.
  Missing first reverse checkpoint means implicit prepared/zero progress, not a
  conflict. Fresh reviews can continue partial reverse known states, writing only
  remaining goal changes within that initial set. A crash after reverse completion
  but before parent ABORTED requires explicit same-action rollback finish.
- Checkpoint publication uses the current writer's fresh `O_EXCL` private scratch
  followed by rename into the canonical checkpoint and directory fsync. Recognized
  `.<intent|rollback|rollback-checkpoint>.json.<32-lowercase-hex>.tmp` files are
  ignored as abandoned unpublished artifacts only if owned, `0600`, single-link,
  regular, and bounded to the record limit. They never supply authority. Existing
  scratch cannot be reused, promoted, or deleted, even if its bytes are identical;
  a name collision fails without altering its name/inode/bytes. Unknown/unsafe
  entries conflict. Immutable content-addressed blob reuse is a separate policy.
- Nothing automatically repairs, resumes, rolls back, or deletes evidence.
  Abrupt termination can leave output stages or private scratch alongside an old
  valid checkpoint. Recovery always reloads actual files and needs explicit review.
- Separate file renames are **not pair-atomic**. No reload/live-apply IPC is sent,
  but watchers may auto-reload intermediate mixed output. Canonical hashes and
  compile success establish neither runtime loading nor hostile-race isolation.

### Example usage

For an exclusively temporary test installation, initialize the store, inspect
explicit routes, and build a complete scoped plan before calling
`publish_reviewed(plan, state_root=state, config_root=config)` directly on the
mutating worker. Inspect all result fields. For an interrupted transaction, first
classify actual bytes, explicitly select an allowed action, display the complete
`review_recovery(state, txid, action, config_root=config).plan`, and only then pass
that exact review to `commit_recovery`. A stale review requires fresh preparation.
This is an API sequence, not installation, live activation, or a new CLI command.

### Related files

- `core/transaction_records.py`, `core/transaction_store.py`: immutable evidence,
  reverse-operation records, safe locked sessions, and atomic private checkpoints.
- `core/transaction_inspection.py`, `core/route_approval.py`: actual-byte
   classification and full route/context revalidation.
- `core/scoped_review.py`, `core/scopes.py`, `core/persistence.py`: complete plans,
  fixed scope order, stable reads, and compile-only checks.
- `tests/test_transaction_publication.py`, `tests/test_transaction_store.py`:
  temporary-only protocol, failure injection, scratch collision, and real
  process-death recovery coverage. See [validation.md](validation.md) for status.

## M3.6a transaction recovery frontend and legacy exclusion

### Overview

This delivered slice provides explicit journal recovery and its own assessment.
Current startup uses `EditorEntry` above, not recovery actual-conflict rows to exclude
healthy pairs. Deferred foreign preservation is not a canonical-only migration
prerequisite; migration/provisioning remain separate work.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `layout_guard.block_reason(config_root, state_root)` | Metadata-only v1 exclusion. Any registry or nonempty transaction directory blocks, including terminal evidence. Unsafe/uninspectable metadata returns a blocking reason. |
| `scoped_recovery.LayoutAssessment` | Strict immutable context, mode, registry condition/canonical pair, bounded transaction rows, truncation, and notes. Modes are `legacy-clear`, `scope-recovery-required`, and `blocked`. |
| `scoped_recovery.run_assess(...)` | Read-only isolated child, default 15-second deadline, one-MiB assessment transport, at most 32 rows; context echo is checked. |
| `scoped_recovery.run_prepare_action(..., txid, action)` | Read-only isolated child, default 30-second deadline; returns a strict `ScopedRecoveryDraft` binding action/context, private digest, snapshot/original review identities, and complete `GroupReviewPlan`. |
| `scoped_recovery.commit_action(draft)` | Direct non-daemon mutator; reconstructs and freshly rechecks the draft before backend delegation. Preserves independent backend uncertainty flags. No commit child/CLI exists. |
| `ScopeRecoveryPage` | Separate assessment, review, and commit actions, lifecycle cancellation, one read slot, close veto during writes, and owner callbacks for exclusion/invalidation. |

### Data Flow

1. `main.py` presents Checking Attune Layout before editor construction. A
   non-daemon thread supervises read-only `editor_layout.run_entry` off GTK.
   `legacy-clear` proceeds to v1, `pair-ready` to the pair editor; blocked results/errors open a recovery
   shell with Scope Recovery, Legacy Backups (v1), Health, and Retry Startup Check.
   Nothing initializes or repairs the store or automatically invokes a mutator.
2. The assessment reports registry/canonical identities and verified or invalid
   transaction rows, actual status, advisory phase, and recorded rollback direction.
   It does not establish runtime loading, publication history, or write authority.
3. Explicit action preparation asks the backend for resume, rollback, finalize,
   or abandon. It verifies private evidence stability and transports a complete
   CURRENT -> GOAL review. GTK renders both scopes, including unchanged scopes,
   lexical/resolved paths, hashes/content IDs, diffs, and evidence identities.
4. A separate commit consumes the draft and rechecks permission. Dirty edits and
   pending monitor previews block it. Window ownership excludes legacy restoration
   and scoped recovery from one another. The commit is direct on a non-daemon
   worker, never a timeout-killed child; GTK does not join it and closure is vetoed.
5. Scope and journal flags accumulate independently and remain sticky on the page.
   Either uncertainty invalidates the cache/editor without marking old baselines
   saved. Unexpected worker exceptions conservatively set both. A new action
    requires a fresh review; refresh assessment to update advisory rows. Invalidated
    editor state does not itself prohibit subsequent explicit journal recovery.

### Edge Cases

- Terminal rows can be observed but cannot be replayed. Conflicts, stale reviews,
  locked rollback direction, or incompatible actual bytes refuse preparation or
  commit. Action buttons are not evidence that every action is allowed.
- Registry evidence alone excludes v1, even if valid and no transaction is pending.
  Terminal transaction history also excludes v1 with no registry. An empty safe
  transaction directory alone does not block; unsafe ancestors, links, permissions,
  inspection failures, and truncated assessments fail closed. Absence proves no
  runtime loader choice.
- `persistence._persist_snapshot` rechecks layout exclusion before side effects,
  under its lock, and before replacement. This covers v1 save, restoration, and
  preservation-first recovery, independently of startup or cached UI observations.
  `LayoutBlockedError` reports no output replacement and clean scope/journal flags.
  Failures later in a write can still leave locks/evidence; no cleanup is implied.
- Discovery of scoped evidence or failed reassessment in a running legacy window
  invalidates caches and disables editing while retaining pending changes. A failed
  assessment also revokes stale transaction rows and reviews. Owner-aware finish callbacks
  prevent a refused legacy attempt from releasing a scope writer's exclusion gate.
- Read cancellation/closure rejects late callbacks and retains the read slot until
  completion, preventing overlapping page children. Mutating filesystem work has
  no hard total deadline despite five-second lock and ten-second compile limits.
- Legacy backup inspection remains available, but v1 bundles are not implicitly
  converted to v2 scopes. Separate renames are not pair-atomic. No reload IPC is
  sent; watchers may load intermediate changed files. Hashes and compilation are
  not proof of Lua semantics, runtime loading, or hostile-race isolation.

### Example usage

In the recovery shell, open Scope Recovery, refresh assessment, select a transaction
and Review rollback (or another permitted action), inspect both CURRENT -> GOAL
scope reviews, then explicitly choose Commit Reviewed Scope Recovery. Cancel writes
nothing. After an outcome, inspect its pending and independent uncertainty fields,
refresh, and prepare a fresh review before further recovery. Do not delete evidence
to force legacy entry or treat Retry Startup Check as migration or activation.

### Related files

- `hyprmod/core/scoped_recovery.py`, `hyprmod/core/layout_guard.py`: service DTOs,
  supervised reads, explicit commit, and metadata-only exclusion.
- `hyprmod/pages/scope_recovery.py`, `hyprmod/main.py`, `hyprmod/window.py`:
  review rendering, startup gate, writer ownership, lifecycle, and invalidation.
- `tests/test_scoped_recovery.py`, `tests/test_layout_guard.py`,
  `tests/test_startup_layout.py`, `tests/test_scope_recovery_gui.py`: coverage;
  M3.6a validation results are recorded in [validation.md](validation.md).

## M3.6b1 read-only scoped restore preparation

### Overview

This first bounded M3.6b slice is implemented and validated.
Its preparation APIs in `core/scoped_restore.py` are read-only.
B2 adds historical browsing/read-only review below, implemented and validated.
Canonical restore b1-b4 is delivered; automatic foreign preservation is deferred.
B3 supplies the separate backend commit API below; b4 supplies its distinct GUI action.
There is no commit CLI.
Ordinary ownership and active editor routing are unchanged.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `prepare_restore(config_root, state_root, txid, scope, side)` | Direct read-only I/O; explicit normalized absolute roots, transaction ID, typed `Scope`, and `prior`/`proposed` selection. Invoke off GTK. |
| `run_prepare(..., cancel_event=None, timeout=30)` | Isolated `-I -B` read-only child with process-group cleanup, cancellation, finite positive deadline, eight-MiB stdout cap, strict decoding, and exact context/selection echo checking. |
| `ScopedRestoreDraft` | Frozen/slotted context and selection, source private digest, terminal phase, historical snapshot/ID, recomputed selected `BackupDescriptor`, and complete both-scope `GroupReviewPlan`. |
| `transaction_store.refuse_pending_readonly(state_root)` | Requires an existing safe initialized store; verifies every bounded journal, refuses corrupt or unresolved evidence, and returns sorted IDs without acquiring/creating a lock or provisioning state. |

The internal worker requires an explicit `prepare` or `list` subcommand.
`prepare` requires both roots plus `--txid`, `--scope`, and `--side`; `list`
requires both roots only. Neither mode can commit.

Draft JSON uses exact schema-1 `scoped-restore-draft` fields and pure nested
semantic validation. Unknown/duplicate fields, invalid types/constants, inconsistent
hashes/diffs/counts/goals, and excessive nesting are refused. The aggregate eight-MiB
limit also applies to canonical ASCII-escaped transport, not just input UTF-8 bytes.
Existing per-side 256-KiB/10,000-line and per-scope complete-diff 256-KiB/4,000-line
bounds remain; oversize reviews refuse rather than truncate.

### Data Flow

1. Verify all pending evidence read-only, then load the complete selected source,
   including both scopes' prior/proposed blobs. Require COMMITTED or ABORTED and
   capture the verified private fingerprint digest. Either historical side can be
   selected; terminal phase does not prove that side was ever installed.
2. Verify selected historical canonical bytes/hash/scope and inspect the current
   registered canonical v2 pair. Require exact roots and registry evidence equality,
   plus both historical `route_binding()` values. These retain paths, links,
   ancestors, and Git context but exclude resolved regular-leaf identity, allowing
   safe canonical leaf replacements and later terminal history.
3. Build a fresh complete CURRENT -> GOAL plan. Only the selected scope takes exact
   historical prior/proposed bytes; the sibling takes its exact **current** bytes,
   not its historical bytes. Recompute descriptor and all plan semantics.
4. Rescan all journals, require unchanged IDs, reload/fingerprint the source, validate
   draft transport, and freshly revalidate the current group review before returning.

### Edge Cases

- Missing/unsafe/uninitialized stores, corrupt/unresolved journals (even unrelated
  or terminal corrupt history), damaged selected or unselected blobs, changed
  registry/routes, and noncanonical current selected/sibling output refuse.
- No-ops still perform all checks and return an empty changed-scope set. All
  preparation is mutation-free: no new lock, snapshot, blob, journal, chmod,
  compilation, Lua execution, main-config read, IPC, or provisioning. Reads may
  update atime; direct I/O has no hard wall-time bound.
- Fingerprints and terminal phases are non-atomic local observations, not
  authentication, publication-history proof, or write permits. Pure draft decoding
  does not establish filesystem freshness. B3's separate writer below freshly
  verifies source evidence under its own lock; b1 adds no writer.
- Foreign current text is not admitted or preserved. Canonical-only snapshots,
  reviews, and compiler paths cannot accept raw foreign rollback blobs. A distinct
  observation/preservation protocol is required, as recorded in ADR 0001.

### Example usage

For an already initialized, exclusively temporary test installation with a verified
terminal transaction ID, call off GTK:

```python
draft = scoped_restore.run_prepare(config_root, state_root, txid, Scope.APPEARANCE, "prior")
plan = draft.plan  # Complete CURRENT -> GOAL observation for both scopes; no commit.
```

This API sequence performs no installation or activation. B3 adds a backend writer
below, and b4 adds a separate GUI commit. Foreign-current preservation is deferred,
not required for canonical-only M3.5 migration.

### Related files

- `hyprmod/core/scoped_restore.py`, `tests/test_scoped_restore.py`: preparation,
  strict drafts/worker transport, race/refusal and forbidden-effect regressions.
- `hyprmod/core/transaction_store.py`, `tests/test_transaction_store.py`: verified
  historical evidence, private fingerprints, and lock-free pending checks.
- `hyprmod/core/scoped_review.py`, `hyprmod/core/scoped_backups.py`,
  `hyprmod/core/transaction_records.py`, `hyprmod/core/route_approval.py`: complete
  canonical plans, descriptors, historical route bindings, and fresh installation checks.
- [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility),
  [validation.md](validation.md#m36b1-read-only-scoped-restore-preparation).

## M3.6b2 historical source browsing and read-only review

### Overview

Implemented and validated at the b2 checkpoint. Scope Recovery has separate
**Transaction recovery actions** and **Historical source review** sections. B2
added no historical writer; b4 below adds a distinct commit action without
repurposing transaction recovery. No split editing, activation, or migration is added.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `scoped_restore.list_sources(config_root, state_root)` | Direct read-only observation of existing initialized storage and current canonical routes. Invoke off GTK. |
| `scoped_restore.run_list(..., cancel_event=None, timeout=30)` | Isolated `-I -B` `list` worker, finite positive deadline, cancellation/process-group cleanup, strict 1 MiB transport, and exact context echo. |
| `ScopedRestoreListing` | Frozen/slotted roots, global `observed`/`blocked` status, separate `scan_complete`/`truncated` flags, sorted unique transaction rows, and bounded notes. |
| `RestoreTransactionRow` / `RestoreSourceRow` | Verified/invalid evidence, phase, reviewable/blocked eligibility and notes; verified rows contain exactly four descriptors in fixed scope/prior/proposed order. Invalid rows have no phase or sources. |
| `ScopeRecoveryPage.browse_sources()` / `prepare_source(txid, scope, side)` | Explicit listing, then selection from a globally safe complete listing and reviewable row. Preparation rechecks permission and delegates to `run_prepare`, not a writer. |

Listing DTOs enforce exact schema-1 fields, nested descriptor/type/order invariants,
deep immutability, bounded notes, and the canonical ASCII-escaped 1 MiB limit.
Preparation retains the b1 strict 8 MiB draft and complete per-scope review bounds.

### Data Flow

1. **Browse Historical Sources** explicitly requests listing. Startup assessment
   does not list historical choices or initialize storage. Before and after listing,
   `refuse_pending_readonly` verifies all journals within the 1,000-entry safety
   limit, including evidence outside the display cap. IDs must remain unchanged.
2. Inspect the current installation and describe the first 32 lexically sorted
   transaction IDs, with appearance/displays prior/proposed sources for each verified
   row (at most 128 sources). Recheck displayed private fingerprints and current
   installation evidence before returning.
3. Selecting an eligible source runs fresh b1 preparation. GTK renders the selected
   descriptor, phase, snapshot/original-review/private identities, changed scopes,
   and both complete CURRENT -> GOAL reviews: paths, hashes/content IDs, exact
   precomputed diffs and counts, including the unchanged **current** sibling.
4. Assessment, listing, recovery preparation, and historical preparation share one
   asynchronous read-only slot. Cancellation clears choices/reviews, rejects late
   callbacks, and retains the slot until completion. Historical review clears the
   recovery draft and disables **Commit Reviewed Scope Recovery**. It cannot call
   `commit_action` or acquire writer ownership by preparation alone; a fresh recovery-action review is
    required to return to the existing commit path.
5. Before rendering, completions must match their requested exact DTO type, roots,
   and selection. Unknown/mismatched results and render failures revoke choices and
   drafts. Positive scoped evidence from an observed listing, nonempty history rows,
   or a restore draft notifies the owner to lock any running legacy editor and
   retain pending edits. Blocked empty listings do not spuriously imply installation.

### Edge Cases

- Display truncation alone can coexist with `observed` and `scan_complete=True`;
  it is not an incomplete safety scan. Pending/corrupt evidence anywhere, including
  undisplayed history, globally blocks source review. Unsafe/uninitialized storage,
  oversized/incomplete scans, unsafe current routes, or detected changes fail closed.
- Historical registry/roots/both-route mismatch blocks only that row when global
  inspection is safe. Old terminal transactions may classify as actual conflict
  in transaction recovery after later publications and still be eligible historical
  sources. Historical eligibility is not taken from recovery `actual_status`.
- COMMITTED/ABORTED and hashes are local observations, not authentication, proof
  that either side was installed, Lua/compiler validity, runtime loading, or write
  authority. No-op reviews still recheck all evidence; oversized reviews refuse
  rather than truncate. Pure decoding does not establish filesystem freshness.
- Listing/preparation creates no lock, evidence, state, or output; performs no
  compilation, Lua execution, IPC, or provisioning. Reads may update atime. No
   historical GUI review committed at the b2 checkpoint. B3 adds a separate backend
   writer below; b4 explicitly integrates it. Separate foreign observation/private
    preservation is deferred and nonblocking for canonical-only migration. Canonical snapshots cannot hold raw originals.

### Example usage

In Scope Recovery, choose **Browse Historical Sources**, inspect global scan status
and row eligibility, then **Review appearance prior** (or another scope/side).
Inspect both complete scope reviews. Cancel writes nothing; the transaction recovery
commit remains disabled. Programmatic temporary-fixture callers use `run_list`
before the `run_prepare` sequence above; neither operation provisions an installation.

### Related files

- `hyprmod/core/scoped_restore.py`, `hyprmod/pages/scope_recovery.py`: listing DTOs,
  supervised workers, explicit browsing, and shared read-slot review rendering.
- `hyprmod/core/transaction_store.py`, `hyprmod/core/scoped_review.py`,
  `hyprmod/core/scoped_backups.py`, `hyprmod/core/transaction_records.py`,
  `hyprmod/core/route_approval.py`: complete scans, canonical plans/descriptors,
  private evidence, and route binding/freshness.
- `tests/test_scoped_restore.py`, `tests/test_scope_recovery_gui.py`:
  validated service/worker and isolated widget coverage. See
  [validation.md](validation.md#m36b2-historical-source-browsing-and-read-only-review).

## M3.6b3 canonical backend restore commit

### Overview

Implemented and validated. Explicit `scoped_restore.commit_restore`
can write the selected historical canonical scope through a **new ordinary
transaction**, not replay or modify the terminal source. At the b3 checkpoint,
the b2 historical GUI remained read-only; its transaction recovery commit and backend
`commit_recovery` behavior are unchanged. No commit CLI/child, editor Save routing,
provisioning, activation, foreign preservation, or migration is added.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `scoped_restore.commit_restore(draft, *, cancel_event=None)` | Exact `ScopedRestoreDraft`; invoke directly off GTK on a non-daemon worker, never in a timeout-killable child. Returns delegated `PublicationResult` unchanged. |
| `transaction_publication.publish_reviewed(..., expected_source=None)` | Optional read-only callback rechecks historical source evidence under the shared writer lock. Restore omits `transaction_id`, requiring new allocation rather than explicit PREPARED reuse. |

The original DTO and all nested field types/tuple containers are validated before
semantic validation and strict JSON copying, so normalization cannot hide mutable
original fields. The private copy, not the caller's original, supplies the consumed
plan and source check. Pre-delegation refusal returns clean failed flags; delegated
results and exceptions are not reinterpreted. Callers must honor independent sticky
scope/journal uncertainty and invalidate editors, never mark old baselines Saved.
Only read-only `list`/`prepare` use supervised children with 1 MiB/8 MiB transport
limits and default 30-second deadlines. The mutator has no such wrapper/deadline.

### Data Flow

1. Reject daemon execution, pre-cancellation, malformed/mutable originals, and
   inconsistent draft semantics; then make the validated private copy.
2. Under the existing store lock, freshly rederive the exact CURRENT -> GOAL
   review and refuse unresolved/corrupt evidence. Reload the complete source and
   compare its private identity/byte fingerprint, terminal phase, snapshot ID and
   exact snapshot, registry/roots and both route bindings. Recompute the selected
   descriptor, exact goal text, and selected blob membership; loading/fingerprinting
   also validates every unselected referenced blob.
3. Before creating evidence, run that source check. For changed output allocate a
   new ID, refuse collisions (including dangling entries), and exclusively create
   its ordinary transaction directory. Never fall into explicit PREPARED reuse,
   including a collision arriving after the allocation probe.
4. The existing publisher compile-checks current/desired canonical texts, syncs
   evidence, stages only changed output, and checkpoints publication. Its checks
   repeat the source check through compilation, evidence synchronization, staging,
   and checkpoints. An additional source check follows the final stage-byte read,
   immediately before rename. Current route/intermediate-group checks protect the
   registry, sibling, links, protected paths, and new transaction evidence.
5. Verify and synchronize the final group, checkpoint COMMITTED, and recheck routes
   and source before reporting success. A no-op still checks source/current/pending
   evidence under lock, compile-checks both current scopes, and rechecks before
   success; it creates no snapshot, blob, journal, or stage.

### Edge Cases

- Same-byte identity replacement of source intent/snapshot/selected or unselected
  blobs, registry, or current outputs invalidates the captured evidence. Hashes and
  terminal phase are not authentication or proof either side was installed.
- Only selected-scope bytes change. Sibling bytes/inode/mtime/mode and lexical Stow
  links survive; source transaction evidence is not rewritten. Reads/fsync may
  affect atime. No-ops and clean failures can still create the store lock file.
- Failures after new evidence creation may report a new pending transaction and
  independent scope/journal uncertainty, including after rename or terminal
  recording. Inspect actual state and freshly review an allowed existing recovery
  action for the **new** transaction. Never replay the terminal source, automatically
  roll back, or delete evidence. Restore does not change interruption recovery.
- Five-second lock and ten-second compile limits are not a hard total filesystem
  deadline. No reload/live-apply IPC is sent; watchers may auto-reload changed files.
  Separate renames are not pair-atomic or a hostile-race guarantee.
- Both current scopes must remain canonical. Foreign originals require a separate
  observation/preservation protocol, not raw canonical rollback blobs. M3.6b is not
   complete. B4 below adds the distinct GUI action, implemented and validated;
     b5 below adds diagnostics only; deferred foreign writer work does not block canonical-only migration.

### Example usage

For an already initialized, exclusively temporary fixture, prepare off GTK with
`draft = scoped_restore.run_prepare(config, state, source_id, Scope.APPEARANCE, "prior")`.
Inspect both complete `draft.plan` scope reviews. Only on explicit authorization,
invoke `result = scoped_restore.commit_restore(draft)` directly on the non-daemon
mutating worker and inspect all result fields. If interruption leaves a new pending
ID, prepare a fresh `review_recovery` for that ID before `commit_recovery`.
This is an API sequence, not a GUI action, CLI command, or permission to touch live state.

### Related files

- `hyprmod/core/scoped_restore.py`, `hyprmod/core/transaction_publication.py`:
  original-draft validation, private copy, under-lock source hook, ordinary writer.
- `hyprmod/core/transaction_store.py`, `hyprmod/core/transaction_records.py`,
  `hyprmod/core/scoped_review.py`: evidence identities, exclusive allocation,
  canonical snapshots and exact review semantics.
- `hyprmod/pages/scope_recovery.py`: b4 integrates the separate historical GUI commit below.
- `tests/test_scoped_restore_commit.py`: temporary-only commit/fault/collision and
   real `os._exit` interruption tests. Results are recorded in
  [validation.md](validation.md#m36b3-canonical-backend-restore-commit).

## M3.6b4 explicit GUI historical restore

### Overview

Implemented and validated. **Commit Reviewed Historical Restore**
is distinct from **Commit Reviewed Scope Recovery**. Historical browsing and
preparation stay read-only; only the explicit commit calls the b3 backend. M3.6b
remains incomplete. B5 below adds backend-only foreign-current diagnostics; private
preservation and writer authority remain deferred, nonblocking work. Live GUI behavior is not verified.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `ScopeRecoveryPage.commit_reviewed_restore()` | Consumes only `_restore_draft: ScopedRestoreDraft`, after complete both-scope CURRENT -> GOAL rendering, and calls `scoped_restore.commit_restore`. |
| `ScopeRecoveryPage.commit_reviewed()` | Consumes only `_draft: ScopedRecoveryDraft` and calls `scoped_recovery.commit_action`; neither handler can use the other's review. |
| `_commit_write(callback, transaction_id, action, changed)` | Shared one-use writer lifetime, owner callbacks, direct non-daemon worker, and `PublicationResult` boundary validation. |
| `restore_permission`, `begin_restore`, `finish_restore(invalidate)` | Owner callbacks enforce dirty/monitor-preview and writer exclusion, release ownership, and invalidate caches/editor without marking old baselines Saved. |

Read completions still require the exact requested DTO, roots, and selection before
rendering. The scoped-restore worker CLI has only read-only `list`/`prepare` modes, with
1 MiB/8 MiB transport limits; no mutator CLI or killable commit child is added.

### Data Flow

1. Explicitly browse, select a reviewable historical scope/side, and inspect its
   descriptor/source identities and complete both-scope CURRENT -> GOAL plan. The
   current sibling is retained. Historical review clears the recovery draft and
   disables recovery commit; recovery review clears the historical draft/button.
2. Only the matching commit button captures its draft and enters the shared writer.
   Every attempt consumes both reviews, historical choices, assessment, and action
   rows before rechecking permission and acquiring owner exclusion. Dirty edits,
   pending monitor preview, or another writer refuse without implicit commit.
3. Call the mutator directly on a non-daemon thread. Disable reads, Cancel, and both
   commits; veto closure until completion. The b3 backend rechecks source/current
   evidence under lock and changes only the selected scope via a new transaction,
   or compile-checks/rechecks a no-op without journals/stages. Five-second lock and
   ten-second compiler limits do not bound total filesystem time.
4. Retire the write token before owner callbacks, rejecting duplicate/reentrant
   completion. Validate the result, accumulate independent sticky scope/journal
   flags, and notify the owner. Either flag invalidates the old editor; a later
   clean no-op cannot clear it. Old baselines are never marked Saved.
5. Show the historical source ID separately from the **new restore transaction**
   (or none allocated/unknown), outcome, pending state, and both sticky flags. A
   pending new ID requires fresh assessment and explicit recovery review/commit for
   that new transaction, never replay of the terminal source. There is no automatic
   recovery. Refresh/re-browse and prepare a fresh review before another action.

### Edge Cases

- Accept only exact `PublicationResult`, exact boolean pending/uncertainty flags,
  known string outcome, optional string error, and optional 32-lowercase-hex ID.
  Historical committed results require changed output, a new non-source ID and no
  pending state. Historical no-op requires unchanged output, no ID, no pending and
  clean flags. Historical failure permits a new pending ID, or no ID with clean
  flags and no pending state. Recovery results bind the reviewed ID; success is
  `aborted` for rollback/abandon or `committed` otherwise, with no pending state.
- Missing/invalid results or exceptions after delegation are unknown/untrusted:
  conservatively set both flags and do not trust a returned transaction identity.
  Thread construction/start failure before delegation adds no uncertainty; a start
  implementation raising after entry retains ownership until worker completion.
- `RecoveryWindow` releases only the matching owner before cache invalidation.
  `HyprModWindow` rejects mismatched scope finishes and legacy finishes while scope
  owns the writer. Begin-notification failure rolls back its gate; finish records
  sticky editor invalidation and releases the gate before fallible cache/widget
  notification. Completion cleanup releases the page writer slot even if feedback
  fails. These orderings prevent stranded close vetoes and duplicate completion
   releasing a newer writer.
- Completion is defined before fallible writer-widget setup. A setup exception
  after ownership routes through clean pre-delegation completion, not a stranded
  writer/close veto. Cleanup clears drafts/assessment/listing independently of
  individually guarded container/control operations and releases the page writer
  slot even if a widget raises. Independent review caught this P2 leak; the fix,
  setup/cleanup regressions, and reentrant-owner checks passed validation with no
  remaining blocking findings.
- Preparation is not write authority or installed/runtime/compiler proof. Both
  current scopes must be canonical; no unknown raw bytes enter canonical priors.
  The separate foreign observation/private-preservation-first protocol is still
  required. No reload IPC is sent, but watchers may auto-reload. Separate renames
  are not pair-atomic.

### Example usage

In Scope Recovery, choose **Browse Historical Sources**, then an eligible **Review
appearance prior** (or another scope/side). Inspect both complete scope reviews.
Only **Commit Reviewed Historical Restore** writes. If the outcome reports a new
pending restore transaction, choose **Refresh Scope Assessment**, review an allowed
recovery action for that **new** ID, inspect both scopes again, and explicitly choose
**Commit Reviewed Scope Recovery**. Do not delete evidence or replay the old source.
This describes the code path, not a live-verified workflow or permission to mutate user state.

### Related files

- `hyprmod/pages/scope_recovery.py`: separate drafts/buttons, shared writer/result validator.
- `hyprmod/main.py`, `hyprmod/window.py`: matching-owner release, close veto and sticky locking.
- `hyprmod/core/scoped_restore.py`, `hyprmod/core/scoped_recovery.py`,
  `hyprmod/core/transaction_publication.py`: immutable drafts and direct mutator contracts.
- `tests/test_scope_recovery_gui.py`, `tests/test_startup_layout.py`,
  `tests/test_restore_window.py`: widget lifetime, result/notification boundaries and ownership.
  See [validation.md](validation.md#m36b4-explicit-gui-historical-restore) for validated results.

## M3.6b5 foreign-current diagnostic observer

### Overview

`core/scoped_foreign.py` is implemented and validated. This is
an inactive backend diagnostic observer, not a foreign recovery draft or writer.
M3.6b remains incomplete; b4's canonical historical restore UI remains available.
Independent review's P2 hidden-unsupported-version finding is resolved by the
all-header detection below; final source-only review found no blockers. Parent
validation results are recorded in [validation.md](validation.md#m36b5-foreign-current-diagnostic-observer).

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `observe_current(config_root, state_root, selected_scope)` | Direct read-only I/O off GTK; explicit normalized absolute roots and exact `Scope`. Requires existing registry/routes, not initialized transaction storage. |
| `revalidate_current(observation)` | Validates the original immutable DTO, then recaptures filesystem/bytes and rejects changed `observation_hash`; returns a fresh observation. It does not make a JSON copy. |
| `run_observe(..., cancel_event=None, timeout=30)` | Isolated `-I -B` observe-only child, finite positive deadline, cancellation/process-group cleanup, 8 MiB stdout cap, strict decoding and exact roots/selected-scope echo. No parent filesystem reread after transport. |
| `ScopedForeignObservation` | Frozen/slotted roots, selected scope, registry `FileEvidence`, raw selected evidence, canonical sibling evidence, four protected `PathProof`s and UTC `observed_at`. |
| `ForeignCurrentEvidence` | Selected scope, `FileEvidence` (raw SHA-256/path/Git proofs), `foreign` or `invalid-scoped` status, and exact text. No canonical content ID or counts. |
| `CanonicalSiblingEvidence` | Exact text plus opposite-scope canonical v2 `RouteEvidence`, full byte hash, content ID and counts ordered values/Beziers/animations/monitors. |

`to_json` / `from_json` enforce exact schema-1 `scoped-foreign-observation`
fields, duplicate/unknown-field and invalid-constant rejection, exact nested types
and tuple immutability, text/hash/leaf-size/classification consistency, canonical
sibling ID/counts, context and UTC semantics. Original nested types are checked
before `asdict`/JSON can hide mutable inputs. `observation_hash` binds substantive
fields but excludes `observed_at`. Pure decoding and a recomputed hash are not
filesystem authentication, freshness, write authority or runtime proof.

Limits: nonempty text at most 1 MiB per scope; selected text at most 10,000
`splitlines()` lines; metadata excluding both texts at most 1 MiB; total transport
at most 8 MiB, including canonical ASCII escaping; JSON nesting at most 24.
Strict UTF-8 rejects invalid encodings/surrogates and C0/C1 controls except tab,
CR and LF. No newline, BOM or Unicode normalization occurs. Admitted text encodes
back to the exact input bytes, preserving CRLF and presence/absence of a final newline.

### Data Flow

1. Private `route_approval._collect_filesystem` captures registry, both route bytes
   and proofs, protected-path metadata and Git context using the existing policy.
   No public `allow_foreign` flag is added. Registry `0600`, owned single-link safe
   regular outputs/parents, declared resolution/basenames, Stow links, collision/
   alias guards, and registry/display outside-Git rules remain enforced. Main Lua
   is metadata-only, never read. State absence is allowed, unsafe dependent metadata
   is not exempted.
2. Classify selected text via `scoped_config.read_document(text)` **without**
   `expected_scope` first. Correct-scope canonical v2 requires canonical restore;
   wrong-scope canonical v2 refuses as cross-scope; canonical v1 requires explicit
   conversion. None becomes foreign. On canonical parse failure, scan **all**
   recognized Attune record-header lines, independent of whole-file prefix.
   A leading run of BOM U+FEFF/ASCII space/tab is permitted for header detection
   only. Explicit unsupported header versions, or known v1/v2 headers containing
   decoded JSON integer versions outside v1/v2, refuse. Leading comments, blank
   lines or BOM cannot hide those records. Raw text is never normalized, and
   exact-marker ownership classification remains unchanged. Otherwise text beginning
   with the exact LF ownership marker is `invalid-scoped`; other admitted text is
   `foreign` (including a CRLF marker variant). Malformed records never supply IDs.
3. Require the opposite sibling to be correctly scoped canonical v2 and construct
   the semantically validated observation. Recheck all collected dependencies
   after parsing, then recollect and require identical filesystem/byte collection.
   The canonical `inspect_installation` consumer still requires **both** canonical
   scopes and independently final-rechecks dependencies after parsing.
4. `revalidate_current` repeats observation and compares substantive hashes. The
   supervised wrapper decodes the child response and verifies exact requested
   roots/selection without adding unbounded parent filesystem work.

### Edge Cases

- Transaction contents are **UNASSESSED**: no transaction directory scan, journal
  read, pending/corrupt classification or lock acquisition occurs. Missing store
  initialization and pending/corrupt journals do not themselves block diagnostics.
  This never authorizes writes, clears conflicts, or bypasses protected-path or
  legacy-exclusion policy. Protected state-path metadata is still checked.
- Missing/empty/binary/oversized/unsafe selected files and noncanonical or wrong-scope
  siblings refuse. Dependency drift, same-byte link retargeting, registry changes,
  permissions, new Git markers and protected-context changes require a new observation.
- No preservation storage, source/candidate selection, proposal, diff, commit,
  GUI activation, provisioning, main Lua parsing, compiler invocation or IPC is
  added. V1 fixtures and ordinary ownership remain unchanged. Reads may affect atime;
  direct I/O has no hard latency bound and observations are not atomic snapshots
  or hostile-race guarantees.
- Deferred work is separately designing raw-preservation evidence, journal/review contracts,
  and writer authority under lock, including pending-conflict checks, before a
  foreign mutator, not canonical-only migration. Raw originals must never enter canonical-only
  snapshots, rollback blobs, reviews or compiler paths.

### Example usage

For an exclusively temporary fixture with an existing safe registry, bounded
foreign selected file and canonical sibling, call off GTK:

```python
observation = scoped_foreign.run_observe(config_root, state_root, Scope.APPEARANCE)
status = observation.selected.status
raw_hash = observation.selected.file.source_sha256
fresh = scoped_foreign.revalidate_current(observation)  # Direct I/O off GTK too.
```

This observes only, initializes nothing and grants no permission to replace text.
The internal worker has only explicit `observe` mode with both roots and scope
required, not a public launcher command or mutator CLI.

### Related files

- `hyprmod/core/scoped_foreign.py`, `tests/test_scoped_foreign.py`: DTOs, worker,
  classification, exact-byte, transport, drift and forbidden-effect coverage.
- `hyprmod/core/route_approval.py`, `tests/test_route_approval.py`: private collector,
  common filesystem policy and strict canonical consumer.
- `hyprmod/core/scoped_config.py`, `hyprmod/core/installation.py`,
  `hyprmod/core/scopes.py`, `hyprmod/core/health.py`: codec, registry/types and supervisor.
- [validation.md](validation.md#m36b5-foreign-current-diagnostic-observer),
  [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility).

## Data Flow

The following flow and v1 ownership/path details describe **legacy mode**. The
existing-pair flow above does not use the v1 cache or writer.

1. **Startup:** only after bounded editor inspection admits legacy entry, the window
   warms the managed cache using the restricted reader,
   constructs IPC-only `HyprlandState` with an empty `/dev/null` document rather
   than executing any Lua, and loads a version-aware, filtered schema. Supported live options
   seed session baselines. Startup does not reload the compositor, migrate main
   config, insert load lines, or register desktop files.
2. **Preview:** widgets apply supported values through IPC. `AppState` tracks
   value and ownership changes; animation and monitor pages contribute section
    drafts. A monitor preview must be kept or reverted before navigation/save/close.
   Runtime changes do not imply any disk write.
3. **Review:** Pending Changes combines option/section changes with a unified
   saved-to-proposed file diff. `collect_save_sections()` gathers monitor and
   animation drafts where managed or edited, and definitions of used curves.
    Managed scalar values come from `AppState.get_all_live_values()`, preserving
    canonical disk values unless explicitly edited. Disconnected monitor records
    and unchanged curve definitions are retained, not reconstructed from IPC. The review
   therefore covers complete emitted output, not just this session's edits.
4. **Persistence:** compare the current snapshot to the reviewed one, reconstruct
   canonical text, compile-check it, and compare saved bytes. Take an advisory
   state-directory lock, recheck destination/content, validate previous nonempty
   ownership/syntax, and back up previous bytes. Recheck before atomic replacement
   via a temporary file in the resolved target's parent.
5. **UI baseline:** only after persistence succeeds, invalidate the config cache,
    mark visual option/section state saved, clear pending library state and visual
    undo history, retaining the independent bindings baseline, dirty state and history,
   and refresh indicators. This does not force a compositor reload.
6. **Integration:** the user explicitly loads the output from their authored Lua
   config after defaults. Attune does not edit the entrypoint or infer its logic.

### Canonical ownership and backups

Generated output begins with `-- Generated by Attune` followed by
`-- Attune data v1: <base64 JSON>`. The JSON encodes `[values, sections]`.
The reader reconstructs a document from supported data and requires a byte-exact
match with re-rendered output. It does not use the executing Lua reader for this
file. The record is a canonical format check, not an authentication signature.

Previous nonempty canonical content is stored as `<sha256>.lua` in
`$XDG_STATE_HOME/attune/backups`, defaulting to
`~/.local/state/attune/backups`. Identical prior bytes reuse the hash-named backup.
The backup directory is refused if it resolves inside a Git working tree, keeping
rollback data out of version-controlled configuration. The lock is
`$XDG_STATE_HOME/attune/persistence.lock`. A new/empty target has no content backup;
unchanged proposed bytes need no replacement.

## Edge Cases

- Both requested and resolved filenames must be `attune.lua`. Existing regular
  targets and parent/file symlinks are supported, with the links preserved.
  The parent must exist; dangling/cyclic links, hardlinked or non-regular targets,
  and aliases to the default main config are refused.
- Empty provisioned Stow sources are accepted. Nonempty hand-authored files and
  any noncanonical edits to generated output are refused, not merged or executed.
- Review binds both bytes and resolved destination. Retargeting a symlink to a
  different destination with identical bytes still requires another review.
- Locks are advisory and final rechecks are not a hostile-race security guarantee.
- Validation prefers `luac -p -`; otherwise `lua -E` compiles stdin using `load`
  without invoking the chunk. Missing tools, timeouts, syntax errors, ownership
  failures, and backup errors prevent target replacement. Successful compilation
  does not prove that Hyprland accepts the options or their runtime effects.
- Removing a scalar override previews a schema default because the main Lua is
  not parsed. After saving removal, explicitly reload authored configuration to
  recover its actual baseline. Discard restores captured session values, not an
  evaluated main-config fallback. Neither operation means the desktop was never
  changed: preview IPC may already have changed it without a save.
- Offline review/save cannot establish live preview correctness. Headless tests
   and mocked wiring checks do not establish live GTK/Hyprland behavior.
- Curve preset-library saves are separate from reviewed compositor saves. They
  immediately update `$XDG_CONFIG_HOME/attune/user_curves.json`; explicit point
  edits also become pending compositor changes, even for an unchanged curve name.
  Undo/discard restores the compositor draft but leaves saved presets intact.

## Health observation boundary

Health has no dependency on editor state, dirty tracking, undo, or reviewed saving.
Its service code uses no Gio/GTK APIs; importing the package still performs the
inherited GI typelib version setup, so native application dependencies remain
required. The same page is reused in a recovery stack when the editor refuses
foreign/invalid output. Back navigation preserves that recovery screen's Retry.

The collector allowlists `hyprctl` JSON queries for version, configerrors, monitors,
and validated saved scalar keys through `getoption`. Each query has a two-second
deadline and 128 KiB stdout/stderr limits.
Missing sessions/tools, malformed replies, blank error entries, and timeouts are
handled per check. It never interprets `[""]` as a configuration error.

Dedicated output inspection reuses ownership validation, refuses nonregular files,
and reads at most 1 MiB. Backup enumeration stops after 1,000 directory entries;
counts are candidates, not validation or a chronological history. Health does not
invoke Lua validators or create missing state/configuration directories.

`run_snapshot` bounds the full worker to ten seconds, with a two-MiB transport cap.
Check text is bounded to 1,024 characters and 16 detail entries, with explicit
truncation markers. A separate process group covers the collector and inherited
query processes; cleanup cannot cover descendants that deliberately detach.

The page uses one non-daemon worker thread and a cancellation event. Only GLib's main-loop
callback touches GTK. Repeated clicks/programmatic requests cannot overlap, late
results are ignored after closure, and cancellation does not join on the UI thread.
Normal interpreter shutdown waits for the bounded worker to finish process cleanup;
abrupt SIGKILL is outside this lifecycle guarantee.
No background polling, automatic correction, or new public CLI is included.

### Drift and report sharing

The seventh observation compares scalar assignments in the already-validated
document with native typed IPC values. Keys must be in both Attune's visual scope
and the bundled schema. Type/value validation precedes queries. Numeric tolerance
is absolute `1e-6`; gap shorthand and RGBA/ARGB gradients are normalized. Unsupported
types, missing/mismatched response identities, unset values, and failures stay
unknown. Drift has a shared two-second/32-query budget within the existing whole
collector deadline. Differences never claim a broken configuration or file loading.
Monitor/animation directives and Beziers are outside this comparison.

Reports use a separate allowlisted projection rather than serialized snapshots.
Known titles/statuses, validated versions, and numeric summaries are included;
raw paths/errors/configuration, display identities, and drift values are omitted.
The preview freezes text and stale state at creation; later refreshes cannot change
the copied contents. Only the explicit Copy action writes the clipboard. Report
files and unredacted mode are not implemented.

Open Output and Open Folder asynchronously inspect the requested target, resolve
the native default `text/plain` or directory handler, and dispatch Gio-generated
escaped URIs. Attune does not shell out, execute Lua, create targets, or apply
settings. Failures remain local errors, and closure cancels pending Gio requests.
The user's chosen handler can perform its own actions under the OS trust model.

## Backup inspection boundary

`core/backups.py` owns read-only listing and comparison. It shares the public
`health.run_bounded` process supervisor, not Health's IPC collectors. Backup
workers never query the compositor, invoke validators, execute Lua, create missing
directories, or call persistence writers. Frozen listing/comparison records use
strict bounded JSON transport. This is not a restoration service.

The configured root is `$XDG_STATE_HOME/attune/backups`. Operations bind an opened
directory descriptor, accept only lowercase SHA256 `.lua` basenames, and use
relative no-follow reads. Entry symlinks, hardlinks, and nonregular files are
rejected. Stable reads check identity, size, and timestamps. A valid backup must
match its filename hash and canonical ownership before summary or comparison.
Comparison independently re-verifies bytes rather than trusting listing evidence.

Current output uses the existing dedicated-path/alias guards. Owned, foreign, or
invalid UTF-8 current output can be described and compared; unavailable/nonregular
or binary content cannot. Missing files compare as empty only where the parent is
accessible and absence can be established. Foreign content never becomes writable.
Backup/current evidence consists of independent stable reads, not an atomic pair.

Listing caps are 1,000 directory entries, 64 candidates, 1 MiB per file, and
16 MiB total reads. Comparison caps are 256 KiB/10,000 lines per side. The worker
computes both full admitted-input counts and a displayed unified diff, capped at
256 KiB/4,000 lines and 4,096 bytes per row. Truncation/oversize states are explicit.
The supervised ten-second deadline bounds expensive diff work; GTK only renders
the precomputed result. Hash ordering and filesystem mtime are not a save journal.

`BackupsPage` lazily schedules one non-daemon list or compare worker. Refresh and
selection clear old diff output; failed list refresh retains stale rows with
comparison disabled. Generation checks and lifecycle cancellation reject late
callbacks. The same component is available from the recovery stack without
constructing editor state. Compare remains inspection-only even though the page
now offers a separate restoration action.

## Reviewed disk restoration

`core/restoration.py` adds an immutable draft binding source basename/hash, resolved
backup root, exact current/proposed text and hashes, lexical/resolved destination,
complete current -> backup diff/counts, and observation time. Both inputs must be
nonempty canonical Attune output within 256 KiB/10,000 lines. Preparation validates
scope and compile-checks Lua without executing it. Its child process can only
prepare; no child/public CLI can commit. The complete review must fit 256 KiB and
4,000 lines. Unlike inspection, truncation is never accepted for restoration.

Commit runs directly in a non-daemon worker. It checks source/root/output bindings
before entering `persist_snapshot`, under the advisory lock, and immediately
before replacement. The shared writer backs up previous output by exclusive
creation of its hash-named file, verifies collisions, and atomically replaces the
resolved destination. Lock waits are cancellable with a five-second limit; each
Lua compile check has a ten-second limit. Arbitrary filesystem I/O does not have a
hard total deadline, and advisory checks are not hostile-race security guarantees.

An unchanged result performs no replacement or backup. A replacement-related error
is conservatively reported as possibly written, never as automatic rollback or
definite cancellation. Managed-data caches are invalidated after success and
uncertain outcomes so recovery Retry constructs state from disk, not old caches.
The ordinary foreign-file overwrite guard remains intact. Normal saves also
invalidate the cache and editor on `PersistenceFailure(may_have_written=True)`;
they do not mark old baselines saved or allow an identical retry to conceal an
uncertain replacement outcome.

The page's explicit restore button is the sole write entry point. Permission is
checked before preparation and again before commit. Dirty edits or pending monitor
confirmation refuse the operation. During commit the editor is insensitive and
close requests are vetoed; the GTK thread never waits for the writer. Successful
replacement or uncertain outcome invalidates cached editor actions until restart.
Read-only utilities remain usable. Save/edit/reset/discard/undo entry points are
guarded before state mutation or IPC; old baselines are never marked saved.

No compositor API is invoked by restoration. This does not prevent Hyprland's own
watcher from auto-reloading changed files. Explicit live application is future
M2.5 work. Foreign/invalid-output recovery uses the distinct M2.6 boundary below.

## Preservation-first recovery boundary

`core/recovery.py` never treats foreign/invalid original text as canonical output.
Its immutable `RecoveryDraft` binds the exact original and candidate bytes/hashes,
original status, source/root/destination identities, complete current-to-candidate
diff, and deterministic private preservation path. Inputs are bounded existing
nonempty UTF-8 text without binary/control characters. Owned output is redirected
to ordinary restoration, not silently admitted here. Only the candidate is
compile-checked. Preparation is read-only and its internal child can never commit.

The separate `persistence.persist_recovery` entry point requires preservation
evidence and a source guard. No `allow_foreign` option exists on ordinary saves.
Under the shared lock, exact original bytes are exclusively created or verified at
`$XDG_STATE_HOME/attune/preserved/<sha256>.bin`. Existing directory/file ownership,
permissions (`0700`/`0600`), single-link regular-file identity, content hash, and
stable reads are enforced. Symlinks, conflicting bytes, unsafe reused permissions,
and storage inside Git are refused. Evidence files and containing directories are
synchronized before replacement; source/current/root bindings are rechecked again
immediately before the resolved atomic replacement.

Raw evidence is separate from canonical backup enumeration and is never offered
as executable or ordinary restoration input. Recovery success/uncertainty clears
managed caches and locks the old editor until restart. The shared atomic writer
also synchronizes the replaced file's directory and reports subsequent errors as
possibly-written outcomes. This is not a hostile-race or hard power-loss guarantee.

The page adds Review Recovery, explicit acknowledgment, and Preserve and Recover
Reviewed Output, rather than falling back from Compare/Restore. Writer lifecycle,
dirty/monitor exclusion, close veto, and direct non-daemon commit match restoration.
No original text is executed, no compositor commands are issued, and ordinary
foreign-file guards remain intact. A compositor may auto-reload watched output.

## Example usage

See [README.md](../README.md#local-source-setup-and-launch) for dependencies and
local uv setup. In the GUI: edit, keep/revert any monitor preview, press Ctrl+S,
review Pending Changes, then choose **Save Reviewed Appearance / Displays**.
Keybindings use their separate review/action and manual loader instructions above;
the legacy visual loading example below does not load bindings.

After the first save, explicitly add this after authored defaults or at the end
of your own Hyprland Lua entrypoint, only if the config directory is on its module
path and `attune` resolves to the intended file:

```lua
require("attune")
```

Match module loading and auto-reload to your configuration; the UI alternatively
describes `dofile` with an absolute path. Reload deliberately and verify compositor
errors/behavior. No automatic include editing, Stow provisioning, registration,
or live UI verification is implied by this documentation.

## Related files

- `hyprmod/main.py`, `hyprmod/window.py`: application lifecycle and orchestration.
- `hyprmod/core/focused_ui.py`: schema scope and `ReviewSnapshot`.
- `hyprmod/core/state.py`, `hyprmod/core/undo.py`: option state and undo history.
- `hyprmod/core/config.py`, `hyprmod/core/persistence.py`: data and persistence.
- `hyprmod/pages/pending.py`, `hyprmod/pages/section.py`: review and section contract.
- `hyprmod/pages/animations.py`, `hyprmod/pages/monitors/`: supported section editors.
- `hyprmod/pages/settings.py`, `hyprmod/ui/onboarding_dialog.py`: read-only guidance.
- `hyprmod/core/backups.py`, `hyprmod/pages/backups.py`: backup inspection boundary.
- `hyprmod/core/restoration.py`, `tests/test_restoration.py`,
  `tests/test_restore_window.py`: restoration transaction and editor exclusion gate.
- `hyprmod/core/recovery.py`, `tests/test_recovery.py`,
  `tests/test_recovery_window.py`: private evidence and explicit foreign-text recovery.
- `tests/test_attune_persistence.py`, `tests/test_attune_sections.py`,
  `tests/test_focused_ui.py`, `tests/test_focused_window.py`: boundary and wiring tests.
- [CONTRIBUTING.md](../CONTRIBUTING.md): checks and manual verification requirements.
- [validation.md](validation.md): current automated and read-only live evidence.
