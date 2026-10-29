# ADR 0001: Shared appearance and machine-local displays

- Status: accepted; data and read-only inspection foundations implemented, split layout not activated
- Date: 2026-10-27
- Roadmap: M3.1; follow-on implementation spans M3.2-M3.6
- Runtime rollout: gated by M0 acceptance and an explicit, reviewed migration

## Context

Attune currently writes one canonical v1 `attune.lua`. Its supported scalar
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
Its schema has an inactive pure parser and a separate explicit read-only filesystem
inspector. No registry file is created or read by the active app. Activation and
write authorization remain future work.

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

An absent registry preserves current legacy v1 behavior only when no blocking
transaction or migration handoff is pending. Startup checks that durable state
first. A present but invalid registry blocks writes and exposes diagnostics; it
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

Foreign initial targets are not admitted as ordinary migration priors. Resolve
them through a separate scope-aware preservation-first review before migration
can proceed. Raw evidence never becomes a canonical rollback blob implicitly.
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

Startup and Health report unresolved transactions and block editing. They never
resume, roll back, finalize, or delete evidence automatically. Read actual output
hashes and bindings; journal progress alone is insufficient after a crash.

| Observed registered outputs | Explicit reviewed action |
| --- | --- |
| All expected prior hashes | Abandon the prepared transaction or resume its reviewed changed scopes |
| All expected proposed hashes | Verify evidence and finalize the journal without rewriting outputs |
| Known prior/proposed mixture | Resume remaining changed scopes, or roll back changed scopes currently at proposed bytes |
| Unexpected bytes, missing/corrupt evidence, changed registry/route | Conflict; refuse automated overwrite and require fresh preservation-first review or manual intervention |

These are designs for future recovery APIs, not currently available buttons.
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

Extend M2.6 preservation-first recovery explicitly to registered v2 scopes. Keep
foreign originals private and separate from canonical blobs, bind scope and route
identity into preservation evidence, and verify/synchronize it before replacement.
Do not relax ordinary ownership guards or admit unknown files as scope payloads.

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
   exact review, while foreign targets require a separate preservation-first
   operation before migration can proceed.
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

- M3.2 (implemented, inactive): pure scoped models, strict structural registry
  validation, v1/v2 readers/renderers, explicit partition, and frozen v1 fixtures.
  Existing v1 behavior remains the only active write mode.
- M3.3a (implemented, inactive): explicit read-only destination inspection and
  transient evidence revalidation, without provisioning or write authority.
- M3.3b-M3.4: scope-aware group review/backup/diagnostic adapters, private evidence,
  journaled writer, interruption classification, and explicit recovery tests.
- M3.6: scope-aware diagnostics, backup/restore/preservation, cache/exclusion,
  and recovery UI before migration is offered. Implement this ahead of rollout
  even though its roadmap number follows M3.5.
- M3.5: reviewed migration/handoff after prerequisites and manual M0 acceptance.

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
M3.2 work implements inactive pure models and codecs, not a registry file, journal,
split writer, or loader. No current output or live configuration has changed, and
no permission for state-changing validation is implied. See
[architecture.md](../architecture.md) for implemented APIs and
[ROADMAP.md](../../ROADMAP.md) for remaining work.
