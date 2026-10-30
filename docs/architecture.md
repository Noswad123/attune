# Attune architecture

## Overview

Attune is the focused appearance/monitor fork of BlueManCZ/hyprmod at `b475087`.
The public executable is `attune`; the Python package remains `hyprmod`.
Upstream attribution and GPL-3.0-or-later licensing are retained in [LICENSE](../LICENSE).

The supported GUI is constrained before page construction, state registration,
and search indexing. It exposes general visual options (gaps, border size/colors),
decoration, animations/beziers, monitors, Pending Changes, and read-only Settings.
Health is an independent read-only utility, also available from startup recovery.
Backup inspection is another independent read-only utility. Its separate disk
restoration workflow participates in the editor exclusion gate, not ordinary
dirty/undo contributions or live preview.
Inherited profile, binding, rule, workspace, autostart, environment, plugin, and
generic configuration helpers are not the focused application's feature contract.
Hand-authored behavior remains outside the GUI.

The first milestone has **one output file for both monitors and appearance**.
A shared/machine-specific split is not active editor routing. Split publication
remains separate from GUI Save; M3.6a integrates only startup assessment and
explicit transaction recovery from the backend.
The selected future design is
[ADR 0001](decisions/0001-shared-local-ownership.md). It chooses two explicitly
registered scope outputs and journaled recovery, with manual loader handoff and
no claim of pair-atomic or runtime snapshot loading. The interfaces below remain
the active single-output implementation unless explicitly labeled inactive.
M3.2's pure models and codec are implemented separately below. Startup now inspects
the configured registry and private journals without selecting a split editor,
activating a registry, or creating state. Explicit recovery may write v2 scopes.

## API / Interfaces

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
evaluation, registry creation, discovery, or activation. M3.6a consumes them for
assessment/recovery validation, not editor Save or split installation activation.

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

`core/route_approval.py` is used by M3.6a assessment/recovery, not editor routing. Its
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
the journaled writer is implemented below. Only transaction recovery has GUI
integration; v1 remains the sole editor Save format, subject to layout exclusion.

## M3.3b scoped adapters

These core APIs do not activate split editing or new Save routing. M3.6a consumes
group reviews for explicit transaction recovery; backup/diagnostic adapters remain
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
separate private-evidence layer below implements storage; ordinary split
publication still has no editor Save integration.

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
backend, not a new application mode. Explicit mutator calls can replace scope
files and private journals. M3.6a integrates explicit recovery and read-only
startup assessment, not ordinary split publication. Split editor Save, CLI
mutation, registry activation, migration, and v2 editor routing remain unavailable.
M3.6b scope-local backup restore/preservation precedes M3.5 and M0-gated rollout.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `publish_reviewed(plan, *, state_root, config_root, transaction_id=None, cancel_event=None)` | Requires explicit context matching a fresh complete `GroupReviewPlan`; prepares evidence or selects the exact matching PREPARED transaction, then publishes changed scopes. |
| `review_recovery(state_root, txid, action, *, config_root)` | Read-only preparation of a frozen `RecoveryReview` with the full CURRENT -> GOAL group plan and private fingerprint; actions are `resume`, `rollback`, `finalize`, `abandon`. Invalid/conflicting/terminal states raise errors. |
| `commit_recovery(review, *, cancel_event=None)` | Rederives the exact recovery review and private fingerprint under lock before the selected operation. Every attempt requires a fresh review. |
| `PublicationResult` | Frozen `transaction_id`, `outcome`, `pending`, independent `scope_may_have_changed` and `journal_may_have_changed`, plus optional `error`. Outcomes are `no-op`, `committed`, `aborted`, or `failed`. |

The two flags are conservative and sticky within an attempt, not inferred from
each other, outcome, or advisory progress. A journal-only change does not establish
a scope replacement; a failed rename/sync/checkpoint can still mean scopes changed.
Callers **must invalidate editors on scope change or uncertainty**, never
mark old baselines Saved. M3.6a also invalidates on independent journal uncertainty.
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

Completed in code, this slice provides startup assessment and explicit journal
recovery, not a split editor, migration, activation, or scope-local backup restore.
M3.6b v2 backup restore/preservation remains a prerequisite before M3.5 migration.

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
   non-daemon thread supervises read-only assessment off GTK. Only `legacy-clear`
   proceeds to the v1 editor. Scoped/blocked results and errors open a recovery
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
`core/scoped_restore.py` prepares canonical scope-local restore observations only.
M3.6b remains In progress: there is no restore source browser/discovery, frontend,
commit API, or commit CLI. Ordinary ownership and active editor routing are unchanged.

### API / Interfaces

| Interface | Contract |
| --- | --- |
| `prepare_restore(config_root, state_root, txid, scope, side)` | Direct read-only I/O; explicit normalized absolute roots, transaction ID, typed `Scope`, and `prior`/`proposed` selection. Invoke off GTK. |
| `run_prepare(..., cancel_event=None, timeout=30)` | Isolated `-I -B` read-only child with process-group cleanup, cancellation, finite positive deadline, eight-MiB stdout cap, strict decoding, and exact context/selection echo checking. |
| `ScopedRestoreDraft` | Frozen/slotted context and selection, source private digest, terminal phase, historical snapshot/ID, recomputed selected `BackupDescriptor`, and complete both-scope `GroupReviewPlan`. |
| `transaction_store.refuse_pending_readonly(state_root)` | Requires an existing safe initialized store; verifies every bounded journal, refuses corrupt or unresolved evidence, and returns sorted IDs without acquiring/creating a lock or provisioning state. |

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
  does not establish filesystem freshness. Future restore writers must freshly
  verify source evidence under their own lock; no such writer is added here.
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

This API sequence performs no installation or activation. Next work is scoped
source browsing/review and writer source freshness under lock, then the separate
foreign observation/preservation protocol, before M3.5 migration.

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

## Data Flow

1. **Startup:** only after the bounded assessment admits legacy entry, the window
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
   mark option/section state saved, clear pending library state and undo history,
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
review Pending Changes, then choose **Save Reviewed Changes**.

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
