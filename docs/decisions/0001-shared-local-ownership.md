# ADR 0001: Shared appearance and machine-local displays

- Status: accepted; M3.6a transaction recovery frontend/legacy exclusion completed in code; split editing/publication Save inactive
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
Its schema has a pure parser and a separate explicit read-only filesystem
inspector. M3.6a startup assessment reads existing registry evidence without
creating, repairing, or activating it. The backend revalidates explicit routes
under lock; split editing/publication Save and activation remain future work.

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

Extend M2.6 preservation-first recovery explicitly to registered v2 scopes. Keep
foreign originals private and separate from canonical blobs, bind scope and route
identity into preservation evidence, and verify/synchronize it before replacement.
Do not relax ordinary ownership guards or admit unknown files as scope payloads.
M3.6b remains In progress and a prerequisite before M3.5 migration. Its first
bounded b1 slice is implemented and validated: read-only
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
is now implemented and validated. Next is the SEPARATE
foreign-current route observation/private-preservation-first protocol before M3.5 migration.
M3.6b is not complete. Preparation/decoding alone never replace writer rechecks.

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

- M3.2 (implemented foundation): pure scoped models, strict structural registry
  validation, v1/v2 readers/renderers, explicit partition, and frozen v1 fixtures.
  V1 remains the only editor Save format, subject to M3.6a exclusion.
- M3.3a (implemented foundation): explicit read-only destination inspection and
  transient evidence revalidation, without provisioning or write authority.
- M3.3b (implemented foundation): complete scope-aware group reviews, pure legacy/v2
  backup descriptors, and fresh scoped diagnostics with redacted report projection.
- M3.4a (implemented foundation): explicit private evidence storage, ordinary
  present-owned transaction records, historical validation, and actual-byte
  interruption classification. Prepared evidence alone is not publication approval.
- M3.4b (implemented backend; only recovery integrated by M3.6a): guarded publication and explicitly reviewed recovery
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
- M3.6b (In progress): scope-local v2 backup restore and preservation-first
  recovery with complete scope/route review and unchanged-sibling isolation.
  B1 preparation, B2 historical source browsing/read-only both-scope review, and
  B3 canonical backend commit are implemented and validated, not the full milestone.
  B4's distinct GUI action/shared writer lifetime is implemented and validated.
  Next is the separate foreign-current route observation/private-preservation-first
  protocol, not raw unknown bytes in canonical priors.
  Complete before M3.5 migration or recommending split rollout.
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
M3.2-M3.4b work implements models, route checks, private evidence, and an
explicit split writer/recovery backend. M3.6a adds startup assessment and explicit
transaction recovery UI. Recovery can write when committed, but no split editor,
split publication Save, registry activation, migration, or loader is installed.
Test outputs/state are exclusively temporary. No live configuration has changed, and
no permission for state-changing validation is implied. See
[architecture.md](../architecture.md) for implemented APIs and
[ROADMAP.md](../../ROADMAP.md) for remaining work.
