# ADR 0001: Shared appearance and machine-local displays

- Status: accepted; existing registered canonical-pair editing/Save implemented and validated
- Date: 2026-10-27
- Roadmap: M3.1; follow-on implementation spans M3.2-M3.6
- Runtime rollout: M0 acceptance pending; migration/provisioning remain separate explicit work

## Current product decision

**Source UI correction:** implemented and validated. A unified
Keybindings list keeps all 80 rows in stable order; every pencil opens Edit Source
Shortcut. No Delete button, Assign New or Unassigned expander. On the actual installed
default TSV (not Prepared): pencil -> clear Shortcut -> Update Pending -> Review
Source -> Save Source. The same row remains blank after Save/restart and its dialog
opens empty. Pending says Clear shortcut; Disable retains the assigned key off.
Backend/state/schema, installed bridge capabilities and this ADR's ownership/save
boundaries are unchanged; no deployment is needed. Earlier counts below are historical,
not validation of this correction. Its supplied final results are in
[current validation](../validation.md#ui-only-correction-final-validation);
live behavior remains unverified. Entering a key from blank defaults Enabled on.

Deliver normal edit, review, Save, and continued editing for an **existing explicitly
registered canonical pair**, using the mature journaled writer. Do not make automatic
scoped foreign preservation or migration a prerequisite for that path. Current user
priority includes existing Keybindings live acceptance. The user accepted the
offline-validated Input checkpoint and approved narrow Cursor work, now implemented
pending final validation. This is not proof of live Input loading/device behavior.
Rules, startup and environment remain separately scoped later work. Additional
managed bindings and source-aware editing are implemented and validated offline;
source integration deployment is complete with all-80 runtime metadata verified,
while live shortcut behavior acceptance remains pending. Profiles/layout
pages remain off scope. Migration is deferred, not the next feature gate. Automatic
foreign preservation is **deferred, nonblocking** work, not a b6 recovery-foundation
shipping gate. The detailed recovery checkpoints below document support capabilities,
not an obligation to complete every edge case before shipping main features.

### Independent Input addition, shared Devices/Cursor unit

Input is a separate machine-side `$XDG_CONFIG_HOME/hypr/attune-input.lua` with a
typed closed input v1 record, dedicated `input.lock` and private `input-backups`.
It is not shared appearance v2, a third `Scope`, registry member or pair journal
participant. Visual v1/v2 and this ADR's two-scope protocol remain unchanged.
Safe existing Stow/Git output is allowed with an existing safe parent; the user
controls commits and Attune never stages. State/backups remain outside Git.
Bindings and Input share narrow fixed-output safety/review/writer mechanics,
not a generic framework. Source TSV keeps its separate writer and stable UI.

The closed `InputConfig` allowlist now has 23 keys: Devices' existing 15 keys/14
widgets plus eight native Cursor keys/eight widgets. One `InputPage` owns both
views; `build_cursor()` adds a widget, not another draft/baseline/undo owner.
**Save Reviewed Input** requires the complete combined Devices/Cursor review,
invalidated by edits in either view, and saves/adopts both together. Whole-unit
Input Discard restores both, while per-row Discard remains local to that row.
Devices-only canonical bytes and the input v1 record stay unchanged, but older
Attune rejects the new Cursor keys: no downgrade compatibility is implied.

Zoom/timeout's two precise numeric entries require explicit Apply, preserve float
precision in locale-aware round-trip display and offer decimal 0.1 +/− steps that
apply. Unapplied text is outside draft/review and survives unrelated edits/Undo/Redo;
whole-unit Discard and saved adoption remain authoritative. Backend finite/bounded
floats have no grid restriction, but public library emission proof may refuse
precision rather than rewrite it. Existing float spin rows remain unchanged; this
small widget adds no generic framework or new ownership boundary.

Appearance/displays, Input (Devices and Cursor), source shortcuts and additional
bindings remain four independent save units preserving each other's drafts,
baselines and undo. No fifth output, scope, registry member or pair journal is
added. Input uncertainty locks both views, not other units. No input/cursor
preview/mutation IPC or automatic loader/
include/reload is added. Manual `dofile` uses the actual absolute path only after
output exists; persistence is not loading proof. Historical Devices-only offline
validation passed: full pytest **4,632 passed, 483 skipped**; eight isolated Broadway
suites **480 passed, 2 skipped**. The user accepted that checkpoint ("so far so good")
and approved Cursor work with "continue" after Cursor was proposed next, not live
loading/device verification. Cursor final validation remains pending. Theme/size,
environment, `set_cursor`, GSettings and hardware/render controls are excluded;
the inherited theme picker remains inactive. See the
[Input contract](../architecture.md#devices--input) and
[Cursor contract](../architecture.md#cursor-shared-input-view),
[historical Input evidence](../validation.md#deviceinput-validated-offline-user-acceptance-pending)
and [pending Cursor checks](../validation.md#cursor-implemented-final-validation-pending).

Sequential saves retain each unit's own source/Git baseline, draft and undo. A new
review may refresh only safe known sibling-output regular/absent leaf proofs;
paths, symlinks, ancestors, main/bridge/registry and Source installed route stay
strict. Full reviewed evidence is exact under writer lock/final checks, so a
post-review change invalidates Save, never silently rebases it. Only the saving
unit adopts its verified result. Source's narrow `same_source` matching joins its
safety-helper imports/protected-name update without changing its stable UI. Input
rows show Saved/Draft/Runtime/Default origins, and unapplied keyboard-options text
survives unrelated edits while remaining explicitly outside the draft until Apply.

### Independent managed-bindings addition

This ADR continues to govern the two visual scopes, not a third scope or a new
all-files transaction. The new `core/bindings.py` workflow is implemented and
validated and uses fixed `$XDG_CONFIG_HOME/hypr/attune-bindings.lua` in admitted
legacy/pair editors, without migration or registry dependency of its own. Its
`-- Attune bindings data v1: ` record is distinct from visual v1/v2. Authored Lua
callbacks remain untouched; every runtime/opaque entry stays read-only with unproven
origin and only installed-client-reported flags. No main-Lua reading or inferred
ownership is authorized.

**Save Reviewed Keybindings** and **Save Reviewed Appearance / Displays** are
independent units with separate dirty baselines and undo retention, not atomic Save
Everything. Bindings use a dedicated `bindings.lock` and private hash-named
`bindings-backups`, never visual pair journals. Fixed/protected routes, existing
safe parent, Stow preservation, foreign/unknown refusal, compile-only checks, fresh
post-save verification, direct non-daemon lifetime and close veto apply. Bindings
uncertainty locks only bindings, not visual scope/journal state. No foreign import,
repair, override, unbind, live apply or reload is added. First-save guidance requires
manual `dofile` with the actual absolute path only after generated output exists;
Attune edits no include lines. Persistence does not prove loading; watchers may
auto-reload. Full interfaces/flow/edge cases are in
[architecture.md](../architecture.md#managed-keybindings), with automated and isolated
GTK evidence in [validation.md](../validation.md#managed-keybindings-implemented-and-validated).
Full pytest passed (4,026 passed, 299 skipped); all five Broadway suites passed
(296 passed, 2 skipped). Live keyboard/loading acceptance remains unverified.
Validation also records the unexplained empty-file observation, without claiming
its origin. Literal command emission, backup-root Git checks, exact argument
fallback and owned-baseline Revert were corrected and independently rechecked;
these reinforce the existing boundary rather than adding a new scope or protocol.

The owner-approved narrow exception to the no-main-changes contract is an **offline
authored integration candidate** under `integrations/hyprland/jdawson`, not normal
application authority over main Lua. It separates 80 stable-ID key declarations
and descriptions from unchanged callbacks. Existing shortcuts can explicitly open
the prepared TSV now and edit keys/descriptions/enabled state, preserving base metadata/order.
Its complete review/Save is an independent unit, not a visual scope or pair
journal participant; generated managed formats remain unchanged. Normal Attune
never executes/rewrites authored main or unbinds runtime shortcuts. On 2026-11-02,
the user-approved three-file deployment installed reviewed copies through the
preserved Stow route, with watcher risk explicitly accepted before writing.
Read-only inspection observed all 80 catalog descriptions, unchanged keys/flags/native
contexts and zero errors; no explicit reload IPC or callback execution was sent.
Live behavior and M0 acceptance remain pending. Any future write/rollback needs fresh
approval and intervening-change checks because watchers may auto-reload. See the
[source contract](../architecture.md#existing-source-shortcuts) and
[ordered manual plan](../validation.md#source-integration-activation-and-rollback).
Isolated registration equivalence is not live behavior proof. Historical key/description checks
passed: full pytest 4,291 passed, 343 skipped; six Broadway suites 340 passed,
2 skipped with IPC disabled and explicit real publishers temporary only; equivalence
114 passed and source backend 149 passed. Ruff/format, error-level Pyright and
build/help/diff checks passed; baseline GI warnings remain. Independent rechecks
found no blockers. Actual-config-root metadata-only alias protection and immediate
watched-TSV reload warnings reinforce this boundary. Earlier counts above remain
historical; see the validation record for full qualifications.

The true source Delete/unassignment fix is **implemented and validated in code and
isolated tests**. It does not change this ADR's visual scopes or independent save units.
Final full pytest: **4,361 passed, 383 skipped**; six Broadway suites: **380 passed,
2 skipped**. Required Ruff/format and error-level Pyright passed, not GI-warning
clearance; independent review found no material findings. See
[final validation](../validation.md#source-shortcut-delete-versus-disable-implemented-and-validated)
for the final isolated run, earlier-run qualification, warnings and unchanged live hashes.
Delete/blank-field clearing saves exactly empty key without `disabled`, removing
the old combo rather than retaining an off tombstone. Disable separately retains
the assigned key. `assigned` means nonempty key; `enabled` means assigned and not
disabled. Empty+disabled is invalid. All 80 catalog declarations remain, not necessarily
80 assigned bindings; IDs/context/native submap/base flags/order and authored callback
sites stay fixed. No callback source removal, action deletion or main-Lua rewrite.
The former pre-correction UI used Assigned shortcuts (N) and a collapsed Unassigned
actions section with Assign New. The current unified list supersedes that presentation.
Pending Clear shortcut is Removed, assignment Added and Disable/Enable Modified; Undo/Redo/
Discard/Revert preserve enabled, disabled and unassigned states.

The candidate retains first-line `-- Attune source bindings capabilities: disabled-v1`
and adds second-line `-- Attune source bindings capabilities: unassigned-v1`.
Any unassigned proposal requires both markers on selected and relevant actual installed
companions under the existing alias guard. Review and direct commit block unsupported
helpers with an update message, preserving metadata/route binding. Existing valid
assigned data, disabled format and v1 schema are unchanged. Valid saved data with a
compatible bridge preserves unassignment through Save/reopen and repeated configuration
loads without resurrection; absent/broken helpers or invalid catalogs still use whole
defaults. This is not a guarantee under corruption. The approved Delete-capable
bridge-only deployment completed on 2026-11-03 UTC: installed `1d1023aa...` supports
both capabilities, replacing disable-only `0fc1fa9f...`, preserving mappings/main Lua.
The user's installed-default `terminal.t` pencil / clear Shortcut / Update Pending /
Review Source / Save Source needs no deployment. At deployment all 80 remained assigned/enabled;
separate in-memory Delete and Disable reviews passed without persistence. App code is
unchanged; no full suite was rerun. See the
[deployment record](../validation.md#approved-delete-capable-bridge-only-deployment).
Do not perform those actions for the user. Effects occur on configuration load, not
automatic IPC; watcher reload remains unproven. Profiles/layout scope remains unchanged.

The earlier reversible source-disable fix was **implemented and validated in code** through
automated and isolated GTK checks, separately from those historical counts.
Historical disable-only results: full pytest **4,332 passed, 367 skipped**; six Broadway suites
**364 passed, 2 skipped**, IPC disabled, explicit real publishers temporary only;
backend/equivalence **304 passed**, source GUI **68 passed**. Ruff/format, full-tree
error-level Pyright, wheel/candidate syntax/launcher help/diff checks passed;
unfiltered GI warnings remain. Timings, warnings and unchanged live hashes are in
[validation](../validation.md#source-shortcut-disable-fix-implemented-and-validated).
At that checkpoint, `SourceBinding.enabled` derived
from metadata-only `disabled` in the existing flags column, retaining the v1 marker
and all-enabled bytes. Catalog, all 80 IDs/records, contexts, submaps, base flags,
order and callbacks remain immutable; keys/descriptions remain available for restore.
Disable/Enable and the Enabled switch participate in Pending Changes, Undo/Redo,
Discard and Revert. Disabled combos are reusable by enabled source rows; conflicting
re-enable refuses atomically. The updated project bridge accounts for all IDs but
skips `hl.bind` on disabled rows, never forwarding `disabled` as an option.

Old all-enabled data works with both bridges. An old bridge cannot honor the new
token and would fall back to all 80 defaults, so review/commit of disabled proposals
require the companion's first-line `-- Attune source bindings capabilities: disabled-v1`
and captured bridge proof; old/missing helpers explicitly block Save. The resolved
P1 direct-Stow bypass additionally binds `SourceBaseline.installed_route`, a strict
JSON-validated metadata `PathProof` for the actual config-root TSV. Shared resolved
target or device/inode requires both selected and installed companion headers and
protected proofs. Recheck installed route/helpers before state creation, under lock
and before replacement; post-write verification allows only the selected regular
leaf's own identity change, including the aliased installed route. Unrelated offline
editing remains independent; no main Lua reads/evaluation. Direct-writer refusal,
both-new success and stale-route/helper regressions passed. Independent source-only
review confirmed P1 resolved with no blockers. This protects against old-loader
fallback, not a general future-format compatibility guarantee. The user-approved
compatible **bridge-only update is installed**, preserving main Lua and TSV.
All 80 rows remain enabled; no Super+T disable has been performed. Installed-path
observation and an in-memory-only disable review pass without persistence. Stable
runtime metadata does not prove the process loaded the new helper or disabled-key
behavior; the process may retain the old helper until the next config parse.
The then-planned user workflow, superseded by the Delete sequence above, was to restart Attune, confirm
the installed default TSV (not Prepared), Disable `terminal.t`, Review Source
Shortcuts and Save Source. The removal takes
effect on the next configuration load; watcher reload is unproven and Attune sends
no IPC. Ctrl+S or visual Save alone is not source Save; the user may manually reload
after source Save if needed. Do not downgrade to the old helper with disabled data
without fresh compatibility review and user re-enabling of disabled rows or another
safe plan; never restore snapshot TSV over later edits. See the validation record
for deployment evidence. Historical tests were not rerun for this code-unchanged
deployment. This adds no visual scope, foreign repair, profiles or layouts.

Startup now uses `editor_layout.EditorEntry`: `legacy-clear` retains unchanged v1;
`pair-ready` requires a valid registered canonical v2 pair, safe initialized store,
and full bounded verification of terminal journals, including undisplayed history.
Zero journals are allowed. Old terminal `LayoutAssessment` actual-conflicts are not
editor readiness criteria. Local pair models feed normal scalar/section pages without
v1 cache reads. Dirty-only proposals preserve untouched data; complete asynchronous
both-scope review is invalidated by edits. Save publishes the exact review directly
on a non-daemon worker with close veto and writer exclusion. Only a fresh safe
post-read matching exact reviewed goals/routes becomes the baseline before marking
saved, enabling repeated Saves. Failure retains dirty edits; uncertainty locks the
editor. Recovery/restore still invalidate old editors, not mark them saved.

Foreign/invalid/missing scopes, missing/unsafe storage, and pending/corrupt evidence
fail closed. Preserve original files/evidence; use explicit fresh transaction
recovery for pending work, or manually inspect and restore verified canonical scopes
and a safe initialized store, then retry startup. No automatic overwrite or repair
is authorized. Settings reports pair routes and labels Health/Backups as legacy-v1
utilities, not pair diagnostics. Startup/Save create no registry/store/targets,
edit no load lines, send no reload IPC, and add no migration or mutating CLI.
Implementation and automated validation are complete; no live acceptance is claimed.
External file/route changes require manual correction/restoration of registered
canonical files/routes and restart/reopen, not adoption into the original baseline.
Retained edits are session-local and do not survive restart; retry review only for
temporary failures.

## Context

At the original decision checkpoint, Attune wrote one canonical v1 `attune.lua`. Its supported scalar
settings, animation/Bezier definitions, and monitor directives are bundled
together. Existing backups are hashes of that complete file, without scope or
machine identity. Readers, caches, review snapshots, path guards, and recovery
are correspondingly single-output interfaces.

The authored Hyprland baseline also contains settings Attune does not own. For
example, `general.layout`, dwindle, input, cursor, bindings, and startup callbacks
must not be absorbed into shared appearance merely because they appear near it
in the same Lua file. Attune must not execute the baseline to discover defaults.

The desired split is about explicit authority, portability, and isolated changes,
not automatic synchronization. Dotfiles remain authoritative, Stow links must
survive writes, and machine topology must not silently become portable appearance.

## Options considered

| Option | Benefit | Cost |
| --- | --- | --- |
| Two owned Lua outputs with a transaction journal | Small extension of existing persistence, readable Git changes, explicit shared/local ownership | Separate replacements are not atomic together; interruption requires explicit recovery |
| Immutable generations with an atomic manifest pointer | One publication point for a complete disk generation | New loader and lifecycle machinery; awkward shared/local Git ownership; pointer atomicity alone does not establish runtime snapshot semantics |
| Split data sources but retain one generated compositor output | Keeps one file replacement | Adds source/output reconciliation and still rewrites display-containing output during appearance changes |

Choose **two owned outputs with journaled disk transactions**. Do not add a
generation-loader subsystem or pretend a sequence of renames is atomic as a pair.

## 1. Ownership and routing

| Owner / logical scope | Allowed data | Dedicated basename |
| --- | --- | --- |
| Authored baseline | Main Lua and authored modules; all behavior outside Attune's allowlist | Never an Attune write target |
| `appearance` | Existing five general visual options, supported `decoration:*` and `animations:*` scalars, animation definitions, and Beziers | `attune-appearance.lua` |
| `displays` | Monitor directives only, including disconnected/disabled selectors | `attune-displays.lua` |

Scope allowlists remain closed: unsupported fields are rejected even as empty
lists. Appearance cannot contain monitors; displays cannot contain scalars,
animations, or curves. Splitting a document must not infer new ownership from
the authored baseline or currently visible hardware.

An appearance-only save must leave display **bytes, inode, mtime, and permissions**
unchanged, and vice versa. Reading for validation may update filesystem atime.
No-op saves replace neither output. Do not stamp an unchanged sibling with a new
transaction ID or shared generation counter.

## 2. Explicit installation registry

Introduce a local installation registry at
`$XDG_CONFIG_HOME/attune/installation.json`, with `~/.config` as the XDG fallback.
Its schema has a pure parser and a separate explicit read-only filesystem
inspector. M3.6a startup assessment reads existing registry evidence without
creating, repairing, or activating it. The backend revalidates explicit routes
under lock. Current existing-pair Save uses those routes without registry creation
or rebinding; installation/activation remain separate future workflows.

The strict schema has exactly these fields:

```text
schema: 1
layout: "split-v2"
routes:
  appearance:
    lexical_path: <absolute path ending in attune-appearance.lua>
    approved_resolved_path: <absolute path ending in attune-appearance.lua>
  displays:
    lexical_path: <absolute path ending in attune-displays.lua>
    approved_resolved_path: <absolute path ending in attune-displays.lua>
```

Recommended lexical locations for the installation review are:

- Appearance: `$XDG_CONFIG_HOME/hypr/attune-appearance.lua`, explicitly provisioned
  through dotfiles/Stow when desired.
- Displays: `$XDG_CONFIG_HOME/attune/local/attune-displays.lua`, avoiding the common
  case where the entire Hyprland directory resolves into a Git checkout.

The XDG expressions above describe proposed defaults. Registry values themselves
are bounded absolute paths, not shell expressions. Reject unknown/duplicate
fields, relative paths, interpolation, scope aliases, and per-save path overrides.
There is no hostname, username, repository-path, or device-ID discovery.

Both lexical and resolved basenames must match the scope. Preserve approved file
or parent Stow links by replacing only the resolved regular target. Reject
same-file/ancestor route collisions, hardlinks, dangling/cyclic links, nonregular
targets, aliases to main configuration files, and targets aliasing registry/state
evidence. Existing v1 and v2 destinations must not alias one another during migration.

The registry and display output must resolve outside Git working trees for this
first split implementation. Handle `.git` directories and worktree `.git` files;
do not equate an untracked file with an ignored machine-local file. Do not write
`.gitignore`, chmod existing user directories, or silently relocate a target.
Appearance may resolve into tracked dotfiles. Displays may use a local Stow source
outside Git; supporting versioned host-specific display packages is a later,
explicit policy extension, not an implicit exception to machine-local storage.

The registry is a user-owned, non-executable local descriptor, not an output file
or a source of arbitrary read/write authority. Its resolved identity and exact
content hash are part of every review. Creation/rebinding is a separate explicit
installation review; no normal Save changes it. Link retargeting or registry
changes invalidate a review, including identical-byte retargeting.
The first inspector requires private `0600` registry storage and safe owned output
permissions. Its evidence can be revalidated but neither authorizes writing nor
automatically persists a destination approval.

M3.6a permits legacy v1 entry only when no registry or transaction evidence is
present and metadata is safely inspectable. Even terminal transaction history
excludes v1 save/restoration/preservation; absence is not proof of loader choice.
Startup assesses this off GTK before constructing the editor. Migration handoff
precedence described below is still a future M3.5 requirement, not implemented
migration-state inspection. A present but invalid registry blocks writes and exposes diagnostics; it
does not silently fall back to writing v1. Merely finding new filenames does not
activate split mode.

## 3. Canonical v2 format

Retain the generated ownership header and add a distinct v2 data-record prefix.
The versioned record contains `version`, `scope`, restricted `payload`, and a
deterministic scope-local `content_id`. The payload contains that scope's values
and supported sections only.
The M3.2 codec requires exactly `values`, `beziers`, and `animations` for appearance,
or exactly `monitors` for displays, including empty collections. Directive order is
preserved and duplicate directive identities are rejected.

Compute `content_id` over canonical version/scope/payload data, excluding the
identifier itself. Also retain a hash of the complete emitted file bytes for
backups and stale-review checks. These are content identities, not save counters
or runtime activation claims. Put transaction IDs only in private state journals.

Require byte-exact reserialization and agreement between registered destination
and encoded scope. No includes, shell commands, callbacks, or machine/repository
paths belong in generated payloads. Motion output must define required Beziers
before referring animation definitions. Unchanged and disconnected records retain
their existing preservation semantics.

Select readers by explicit format/scope validation, not by falling through to an
executing Lua reader for unfamiliar basenames. Replace global mutable path/cache
assumptions with scope-aware records keyed by registry identity, route bindings,
format, and content identity. Keep v1 reads unchanged and add frozen historical
v1 fixtures; tests generated solely by a new renderer are not compatibility proof.

## 4. Loader boundary and order

The conceptual order is:

```text
authored defaults and modules
    -> registered appearance output
    -> registered display output
```

The user places explicit loading after all authored defaults it should override.
Generated scope files do not load each other. Do not repurpose legacy `attune.lua`
as a loader: existing readers and backups treat it as canonical data, not executable
include logic. Attune does not insert or edit loader lines.

This decision intentionally does not prescribe a working `require`/`dofile`
snippet before validation. Appearance may be module-addressable, while the local
display destination may be outside the Hyprland module path. Resolve that using
documented, tested loader instructions, not a runtime fallback guessed by Attune.

Inherited helper comments claim stronger watcher behavior for `require` than for
`dofile`, but the inspected project has no compositor-source evidence establishing
cache reset, empty-scope loading, or symlink watch behavior across reloads. Those
claims are validation gates, not accepted guarantees. Never infer successful
loading from file presence or matching saved/runtime values.

## 5. Multi-file transaction and recovery

### Review and prerequisites

Review a group containing the registry identity and **both** route bindings,
current bytes/hashes, proposed changed-scope bytes/hashes, complete per-scope
diffs, and a fixed changed-scope set. Normal split saves require both registered
outputs to be present, canonical, and correctly scoped. A damaged sibling blocks
normal group editing until explicit scope-aware recovery; no partially trusted
installation is treated as healthy.

Initial provisioning/migration must explicitly create canonical empty-scope
documents where needed. Empty provisioned files are not silently promoted by
normal group Save. Validate all changed outputs before replacing any of them.

Migration/provisioning journals distinguish prior target states, rather than
collapsing absence and empty bytes into one hash:

- `absent`: approved absence, no prior blob, and no dangling file-level symlink.
  An inverse operation is a separately reviewed unlink of the exact file created
  by this transaction, with current path/content/object-identity guards.
- `present-empty`: exact zero bytes at the approved binding. An inverse operation
  restores empty bytes to the resolved target, preserving any Stow link.
- `present-owned`: verified canonical bytes with scope and blob identity. An
  inverse operation restores those reviewed bytes.

Foreign initial targets are not admitted as ordinary migration priors. The next
canonical-only migration must refuse them and require manual remediation. A future
automated foreign replacement would need a separate preservation-first protocol;
implementing it is not a canonical-only migration prerequisite. Raw evidence never
becomes a canonical rollback blob implicitly.
Journal and directory-sync inverse operations as well as forward replacements.

### Durable evidence and publication

Use private state outside Git for content blobs, group snapshots, and journals:

- Canonical blobs remain content-addressed by full byte hash.
- A group snapshot records both paths, presence, scopes, hashes, verified blob
  references, and changed scopes. It describes a disk observation, not runtime state.
- A transaction journal binds that snapshot, proposed blobs, registry identity,
  approved routes, ordered changed scopes, and progress.

Under the existing bounded advisory lock:

1. Refuse unresolved prior transactions. Revalidate registry, both routes, source
   evidence, exact reviewed current bytes, scope, and compile-only syntax.
2. Persist and verify prior/proposed blobs, group snapshot, and prepared journal.
   Use owned private `0700` directories and `0600` files; synchronize evidence and
   parent-directory entries before the first output replacement.
3. Stage changed files beside their resolved targets and synchronize them. Replace
   changed scopes only, in fixed appearance-then-displays order. Immediately before
   each replacement, check the expected intermediate group state and bindings.
4. Synchronize each output directory and then checkpoint its progress durably.
5. Verify final hashes/bindings and durably mark the journal committed.

Do not implement this by calling the existing single-file transaction twice.
Cancellation before publication leaves outputs unchanged, though evidence may
exist. Cancellation/failure after one replacement leaves an interrupted group,
not an automatic rollback claim. A directory-sync/checkpoint error is uncertain
even if the preceding rename returned successfully.

### Explicit interruption handling

Startup and Scope Recovery report transaction evidence and block legacy editing.
Health remains a separate read-only utility, not the transaction action frontend.
They never
resume, roll back, finalize, or delete evidence automatically. Read actual output
hashes and bindings; journal progress alone is insufficient after a crash.

| Observed registered outputs | Explicit reviewed action |
| --- | --- |
| All expected prior hashes | Abandon the prepared transaction or resume its reviewed changed scopes |
| All expected proposed hashes | Verify evidence and finalize the journal without rewriting outputs |
| Known prior/proposed mixture | Resume remaining changed scopes, or roll back changed scopes currently at proposed bytes |
| Unexpected bytes, missing/corrupt evidence, changed registry/route | Conflict; refuse automated overwrite and require fresh preservation-first review or manual intervention |

M3.4b implements these ordinary present-owned recovery actions. M3.6a exposes
them through Scope Recovery with a complete fresh CURRENT -> GOAL review of both
scopes and a separate explicit commit. Invalid/terminal states and disallowed
actions refuse rather than becoming recovery authority. Migration/provisioning
remains future work.
For migration/provisioning, an explicitly recorded `absent` state counts as the
expected prior state; an unrecorded missing file is a conflict. Empty prior content
is distinct from absence. A guarded unlink is available only for an explicitly
reviewed transaction-created target, never an unchanged sibling or unknown file.
An unchanged scope has the same prior/proposed identity and must never be written
as a side effect of recovery. Appearance-only recovery must not restore displays.
Rollback is itself journaled and crash-resumable. Journal paths are evidence, not
write authorization: every action must still match the approved registry.

Separate replacements can expose mixed files to a compositor watcher or another
reader. Journaling provides disk recoverability, **not pair-atomic publication,
runtime snapshot loading, or live rollback**. Send no reload/live-apply IPC and
warn that watched files may nevertheless auto-reload between replacements.

## 6. Scope-aware backup and preservation compatibility

Keep current hash-named v1 backups readable as **legacy full-bundle** data. Never
reinterpret a legacy bundle as appearance just because that is the active page.
Extracting a legacy scope requires an explicit conversion review with new v2
identity and validation. Cross-scope restoration of v2 data is refused.

Group snapshots supply context and recovery evidence, not permission to restore
all members. A scope-local restore changes only its reviewed scope. A whole-group
restore reviews both outputs and uses the journaled group writer. Unknown formats,
cross-installation routes, and damaged bundles fail closed rather than guessing.

If deferred M2.6 preservation-first recovery is extended to registered v2 scopes, keep
foreign originals private and separate from canonical blobs, bind scope and route
identity into preservation evidence, and verify/synchronize it before replacement.
Do not relax ordinary ownership guards or admit unknown files as scope payloads.
Automatic foreign preservation is deferred, not a prerequisite for existing-pair
editing or canonical-only M3.5 migration. The historical first bounded b1 slice
is implemented and validated: read-only
preparation from an explicitly selected verified terminal transaction's canonical
prior/proposed scope, with a complete CURRENT -> GOAL review preserving the current
sibling. It requires safe initialized storage, canonical current outputs, exact
registry/roots identity and historical both-route bindings, plus before/after
read-only pending checks. Source fingerprints/phase are local observations, not
authentication, proof of installation, or write permits. B1 adds no source
listing/discovery, frontend, commit, compiler, provisioning, or foreign preservation.

The decision is to split canonical restore preparation from foreign recovery.
`GroupSnapshot` admits present-owned canonical priors only; group review derives
scope content IDs and exact canonical bytes for both sides, and ordinary publication
compile-checks current and desired scope text. Foreign current bytes cannot satisfy
those contracts. Smuggling them into raw canonical rollback blobs would misrepresent
ownership and feed untrusted original text into the ordinary compiler path. Do not
relax those invariants or ordinary ownership guards. A separate bounded foreign
observation/review and verified private preservation protocol must bind original
status, bytes, scope, and route before any explicit replacement; raw evidence stays
distinct from canonical backups. That protocol is not implemented by b1.

B2 adds explicit historical source browsing and full both-scope read-only reviews
in ScopeRecoveryPage, implemented and validated. Listing is a user
request, not startup provisioning. The full 1,000-entry journal safety scan is
independent of the 32-transaction/four-source display cap. Display truncation is not
incomplete scanning; pending/corrupt evidence globally blocks. Historical route
incompatibility is row-local when global inspection is safe. An old terminal
transaction's actual-conflict recovery classification is not source eligibility.
Phase/hashes prove neither installed bytes, runtime/compiler validity, nor
authentication. Historical review never populates a recovery draft or enables the
existing transaction recovery commit. Listing/preparation share the page's single
async read-only slot, with bounded 1 MiB/8 MiB worker transport respectively.

B3's canonical backend `commit_restore` is implemented and validated.
It validates the original exact immutable draft before JSON copying, then delegates
to ordinary publication with an under-lock `expected_source` check and a **new
ordinary transaction**. Complete private fingerprints, snapshot/phase/all blobs,
exact review and source/route binding are checked before evidence creation and
through compilation, synchronization, staging/checkpoints, immediately after the
final stage read before rename, and before no-op/final success. Generated ID
collisions refuse, never reuse PREPARED history. The sibling, Stow links, and
historical source evidence remain protected. No-ops still compile/recheck without
journals/stages; the store lock file may be created.

This explicit backend mutator is direct/non-daemon, never a timeout-killable child
or CLI. Delegated result flags are unchanged; callers must invalidate old editors
on scope/journal uncertainty. Failure may leave a new pending transaction requiring
fresh explicit existing recovery, never terminal-source replay. Existing interruption
recovery is unchanged. Lock/compiler limits are not a total filesystem deadline;
no reload IPC does not prevent watcher auto-reload. B2's historical GUI was read-only
at that checkpoint. B4's distinct GUI historical restore action/shared writer lifetime
is now implemented and validated. B5's separate foreign-current diagnostic observer
is implemented and validated. Foreign preservation/writer work remains deferred,
not required before canonical-only M3.5 migration. Preparation/decoding alone never
replace writer rechecks.

B4 requires a complete both-scope CURRENT -> GOAL review and a separate **Commit
Reviewed Historical Restore** consuming only its own `ScopedRestoreDraft`. Existing
transaction recovery retains its own draft/action; listing/preparation never commits
implicitly. Shared direct non-daemon writing rechecks dirty/monitor-preview permission
and exclusion, vetoes closure, consumes reviews/action rows, and validates exact typed
results, transaction IDs, outcomes and boolean flags. Invalid post-delegation results
or exceptions conservatively set both independent sticky uncertainty flags; worker
start failure before delegation adds none. Outcomes distinguish source from new
restore ID. Pending new transactions need fresh assessment and explicit recovery
review/commit for that new ID, never automatic recovery or terminal-source replay.
Matching-owner release and sticky editor locking precede fallible cache/widget
notifications; completion is one-shot so stale callbacks cannot release a newer
owner. Completion is defined before fallible setup; setup exceptions route through
pre-delegation cleanup, with essential authority cleanup independent of individually
guarded widget operations. Independent review's P2 setup-widget leak was fixed and
rechecked with no remaining blocking findings. A fresh refresh/review is required
after attempts. Validated results are recorded in `../validation.md`; live GUI
behavior is not verified. Unknown raw bytes remain outside canonical priors.

B5 adds only `scoped_foreign.observe_current`, `revalidate_current`, and supervised
`run_observe`, returning a distinct frozen `ScopedForeignObservation`, never foreign
`InstallationEvidence`. Selected raw text/hash/path proof/status has no canonical
ID/counts; the opposite canonical sibling retains scope/ID/counts. Strict UTF-8 and
control checks preserve admitted exact bytes, CRLF and final-newline presence.
Bounds are 1 MiB per scope, 10,000 selected lines, 1 MiB metadata, 8 MiB total
ASCII-escaped transport and JSON depth 24, with deep immutable semantic/hash/UTC
and exact context/selection validation. Codec dispatch without expected scope first
refuses canonical same/wrong-scope v2 and v1. After canonical parse failure, scan all
recognized record-header lines independently of whole-file prefix, permitting
leading BOM U+FEFF/ASCII space/tab for detection only. Unsupported header versions
and known headers with embedded JSON integer versions outside v1/v2 refuse, even
after leading comments/blank lines/BOM. Raw bytes and exact-marker status are unchanged.
Malformed exact-marker text is `invalid-scoped`, other admitted text `foreign`.

Private filesystem collection shares existing ownership/permission/link/alias/
protected/Git policy without a public `allow_foreign` flag. Canonical inspection
still requires both canonical scopes and final-rechecks after parsing. Transaction
contents are UNASSESSED, not scanned/read; diagnostics need no initialized store
and may observe alongside pending/corrupt journals. This is not authority, conflict
clearance or a protection bypass. B5 adds no preservation storage, source/candidate,
proposal/diff/commit, GUI activation, provisioning, main Lua read, compiler or IPC.
B4's canonical restore UI, v1 fixtures and ordinary ownership remain unchanged.
For any future foreign mutator, separately design raw-preservation evidence, journal/review contracts and
writer authority under lock, including pending-conflict checks, before a foreign
mutator, not canonical-only migration. This work is parked and nonblocking. See the
[b5 contract](../architecture.md#m36b5-foreign-current-diagnostic-observer).

Successful restore/recovery and any uncertain write invalidate all cached editors
until restart. Read-only utilities remain usable. No old editor baseline is marked
saved, and no keyboard/API undo/reset/discard path may bypass exclusion.

## 7. Opt-in migration from v1

Maintain a durable migration lifecycle separate from the output-write journal:

```text
preparing -> prepared -> handoff-pending -> activated
                  \-> explicit abort
any interrupted/conflicting transition -> migration-pending or conflict
```

An interrupted preparation transaction blocks mutations pending explicit recovery.
A completed `prepared` state is distinguishable from that interruption and leaves
legacy Save available; subsequent legacy changes make the preparation stale, not
permission to refresh split outputs silently. `handoff-pending` is persisted before
asking the user to change loader lines and freezes ordinary writes across restart,
even while the active registry is absent. Migration state takes precedence over
the absent-registry legacy rule.

1. Capture stable canonical v1 bytes/hash/path and confirm M0 integration acceptance.
   Refuse dirty edits, pending monitor confirmation, unsafe routes, foreign v1,
   and unresolved transactions.
2. Explicitly review the local registry and both destinations. New targets may be
   absent or separately provisioned empty files; existing owned targets require
    exact review. Foreign targets are refused with manual-remediation instructions;
    automatic foreign preservation is not required for this canonical-only migration.
3. Split only owned v1 data, preserve disconnected records and required curves,
   validate v2 scopes, and show the exact proposed files and registry transition.
4. Journal and prepare the new files side-by-side, preserving exact legacy evidence.
   Leave the legacy output unchanged and still loadable. Migration preparation
   must not install an active split registry or silently freeze legacy Save.
5. Under the shared lock, revalidate the captured legacy lexical/resolved binding
   and exact bytes/hash, both prepared outputs, and the registry transition. Refuse
   drift and require a fresh split review; do not lose an intervening v1 save.
   Durably enter `handoff-pending` and freeze ordinary writes before releasing the
   lock. Only then ask the user to manually replace the legacy loader entry with
   the two ordered scope entries, avoiding double loading. Provide explicit abort
   instructions that restore the legacy loading choice.
6. Verify the intended integration under explicit permission and separately review
   activation of the local split registry. If activation fails or the app restarts
   mid-handoff, report migration-pending state and offer explicit resume/abort.

Activation rechecks the captured legacy source, prepared outputs, approved paths,
and expected prior registry state under lock. Publish/synchronize the reviewed
registry, then durably checkpoint `activated`. If the registry is published but
that checkpoint is missing, startup classifies the exact registry/output evidence
as activation-pending and keeps all mutations blocked until explicit finalization
or abort. A mismatch is a conflict, not a reason to overwrite or fall back to v1.

Abort must restore the reviewed prior registry state, including guarded removal
of a transaction-published registry if the prior state was absent. After handoff
begins, it must also require the user to restore and confirm the legacy loader
choice before legacy editing is reenabled. Registry absence alone cannot establish
that choice. Prepared scoped files may remain inactive; cleanup or inverse target
operations are explicit and journaled, never arbitrary recursive deletion.

Mere user confirmation is not proof of loader correctness. Runtime checks must be
described as observations with limits. No automatic loader editing, v1 deletion,
registry auto-repair, cleanup, or guessing of the user's authored includes occurs.
The retained legacy file is a historical archive after activation, not a fallback
to silently combine with split mode. Reverting layout requires a reviewed handoff,
not an in-place concatenation of potentially divergent outputs.

## 8. Implementation sequence and acceptance

- M3.2 (implemented foundation): pure scoped models, strict structural registry
  validation, v1/v2 readers/renderers, explicit partition, and frozen v1 fixtures.
  V1 compatibility remains unchanged, subject to legacy layout exclusion.
- M3.3a (implemented foundation): explicit read-only destination inspection and
  transient evidence revalidation, without provisioning or write authority.
- M3.3b (implemented foundation): complete scope-aware group reviews, pure legacy/v2
  backup descriptors, and fresh scoped diagnostics with redacted report projection.
- M3.4a (implemented foundation): explicit private evidence storage, ordinary
  present-owned transaction records, historical validation, and actual-byte
  interruption classification. Prepared evidence alone is not publication approval.
- M3.4b (implemented backend; also used by current existing-pair Save): guarded publication and explicitly reviewed recovery
  with compile preflight and failure/crash tests. Prepared intent alone remains
  insufficient. Rollback has an immutable operation and separate checkpoints in
  the original transaction directory; direction is locked once recorded. All-prior
  abandon closes metadata without a compiler; all-proposed finalize still compiles
  but replaces no scopes. See architecture for API and scratch-file details.
- M3.6a (implemented and validated; live rollout gated): bounded asynchronous
  read-only startup assessment, recovery shell for scoped/blocked/error results,
  and explicit transaction action review/commit. Only `legacy-clear` constructs
  the v1 editor. Read-only children are isolated and bounded; commits are direct
  non-daemon workers with close veto and owner-aware legacy/scope exclusion.
  Independent sticky scope/journal uncertainty invalidates cache/editor without
  marking old baselines saved. Writer-side metadata exclusion fails closed on any
  registry/transaction evidence or uninspectable metadata, including terminal history.
- M3.6b (supporting checkpoints): scope-local canonical restore and diagnostics
  with complete scope/route review and unchanged-sibling isolation.
  B1 preparation, B2 historical source browsing/read-only both-scope review, and
  B3 canonical backend commit are implemented and validated, not the full milestone.
  B4's distinct GUI action/shared writer lifetime is implemented and validated.
  B5's separate backend-only foreign-current diagnostic observer is implemented and
  validated. Automatic raw preservation/writer work is deferred and nonblocking;
  unknown bytes never enter canonical priors.
- Existing canonical-pair normal editing/review/Save/continue: implemented and
  validated. Reuse the mature writer and verify exact fresh baselines.
- M3.5: deferred canonical-only reviewed migration/handoff, separate from initial
  provisioning support and subject to explicit manual acceptance. Foreign preservation
  is not a prerequisite.

Required tests include scope rejection; frozen v1 compatibility; malformed v2;
route/registry aliases and retargeting; empty-scope provisioning; appearance/display
byte/inode/mtime/permission isolation; no-op behavior; file/parent Stow links; and
private evidence outside Git. Inject failures before/after every replacement,
directory sync, checkpoint, rollback step, and migration transition. Cover all
prior/proposed mixtures, conflicts, missing evidence, cancellation, lock contention,
read-only startup, and preservation of unchanged scopes during recovery.
Include distinct absent/empty priors, guarded unlink versus empty-file restoration,
an intervening v1 save before handoff, restart with no registry during handoff,
registry publication without activation checkpoint, and interrupted/aborted loader
handoffs that must not silently reenable legacy writes.

Runtime rollout additionally requires verified Lua API syntax, loader order/cache
behavior, empty scopes, Stow watches, explicit reload and override removal,
partial-load errors, animation/Bezier dependencies, and display/HDR acceptance.
Do not mark these gates passed from compilation, isolated GTK tests, inherited
helper comments, or this document. M2.5 live application remains separately gated.

## Consequences and non-goals

The design adds explicit installation and transaction state, and can temporarily
block all editing when a sibling output or interrupted group is unhealthy. This
is preferable to silently overwriting damaged state or claiming false atomicity.
The initial outside-Git display policy deliberately excludes versioned host-specific
display packages until an explicit policy extension is designed.

The M3.1 decision itself created no configuration/state files or codec. Subsequent
M3.2-M3.4b work implements models, route checks, private evidence, and an
explicit split writer/recovery backend. M3.6a adds startup assessment and explicit
transaction recovery UI. Existing registered canonical-pair editing and Save are
now implemented and validated. Registry creation/activation, provisioning,
migration, and loader installation are not added by that feature.
Test outputs/state are exclusively temporary. No live configuration has changed, and
no permission for state-changing validation is implied. See
[architecture.md](../architecture.md) for implemented APIs and
[ROADMAP.md](../../ROADMAP.md) for remaining work.
