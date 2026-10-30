# Attune validation record

This records evidence, not a blanket claim of workstation acceptance. State-changing
M0 checks in [ROADMAP.md](../ROADMAP.md) remain pending explicit manual acceptance.

## M1.1-M1.4: read-only Health

Verified during the 2026-10-26 implementation session. The live collector snapshot
was observed at `2026-10-27T00:12:13+00:00` (UTC).

### Automated coverage

- Full suite: 1,292 passed, 9 skipped. Skips include the opt-in GTK smoke suite.
- Isolated Broadway GTK smoke suite: 8 passed, with compositor queries stubbed.
- Ruff lint/format and Pyright error checks passed. GI source-resolution and
  dependency deprecation warnings remain; these are not live behavior checks.
- Health tests cover partial IPC failure, malformed/oversized/nested responses,
  missing tools/session/output/backups, symlinks, nonregular output, read-only
  inspection, collector timeout/cancellation, and subprocess descendant cleanup.
- A subprocess regression verifies immediate normal interpreter exit after closing
  Health still allows cleanup of the collector and its inherited-group descendant.
- UI tests cover single-worker refresh, main-loop responsiveness, stale snapshots,
  late callbacks after closure, recovery Health access, and returning to Retry.

### Read-only live observation

The actual supervised collector, not a stub, reported:

| Check | Observation |
| --- | --- |
| Compositor | Hyprland 0.56.2 reachable |
| Configuration errors | No nonblank error text; the raw query returned `[""]` |
| Display | HDMI-A-1, 2560x1440 at 59.951 Hz, scale 1, position 0,0 |
| Managed output | Missing; its parent resolves into the Stow-managed dotfiles tree |
| Validator | `/usr/bin/luac` found but not invoked |
| Backups | Backup directory absent; nothing created |

Only the allowlisted read-only queries and filesystem inspections were performed.
No settings were applied, Lua executed, compositor reloaded, main configuration
edited, or live desktop window launched for this validation.

### Remaining verification and work

- User-visible Health layout on the actual Wayland desktop has not been manually
  exercised; automated widgets were tested using an isolated Broadway display.
- M0's monitor rollback, HDR, animation previews, persistent loading, and Stow-save
  acceptance are not established by this diagnostics run.
- M1.5-M1.7 were pending at this first checkpoint; their later verification follows.

## M1.5-M1.7: reports, scalar drift, and output actions

### Automated coverage

- Full suite: 1,381 passed, 13 skipped. Twelve skips are opt-in GTK cases.
- Isolated Broadway smoke suite: 12 passed, with clipboard and external launchers
  mocked. Tests exercise both normal and recovery views, frozen report copying,
  Cancel without copying, stale snapshots, escaped URIs, and missing targets/handlers.
- Ruff lint/format, Pyright error checks, and diff whitespace checks passed.
- Pure report tests verify that arbitrary raw strings, paths with spaces, error
  snippets, credentials, display identities, and drift values cannot pass through
  the allowlisted projection.
- Drift tests cover supported type normalization, unsupported keys/types, malformed
  replies, partial query/time budgets, output consistency, and read-only operation.

### Read-only live checks

The seven-check supervised collector and redacted report were exercised against
the running session at `2026-10-27T01:14:25+00:00` (UTC). The real managed output was
still absent, so drift correctly reported unavailable rather than fabricating data.

A disposable canonical `attune.lua` under `/tmp/opencode` then supplied five saved
test values to the actual collector. No live configuration was provisioned or loaded.
Real `getoption` observations returned **5 matching, 0 differing, 0 unknown** for
rounding, opacity, blur-enabled, inner-gap shorthand, and the active-border gradient.
This verified boolean/numeric/CSS-gap/RGBA-to-ARGB normalization with native IPC.
The redacted report omitted the known temporary and home paths. The temporary
owned output was removed by its test context.

### Limitations

- Actual Wayland clipboard copying and launching the user's editor/file manager
  were not performed. Their GTK/native API wiring was tested with isolated mocks.
- Drift is limited to supported saved scalar types. Definition-level animation,
  Bezier, and monitor comparison is not implemented.
- A matching saved/runtime value does not establish that Attune's file was loaded.
  No last-save timestamp is recorded or claimed.
- M0 state-changing acceptance remains pending. No compositor settings, authored
  files, desktop registrations, or services were changed by these checks.

## M2.1-M2.2: read-only backup browser and comparison

### Automated coverage

- Full suite: 1,460 passed, 19 skipped. Eighteen skips are opt-in GTK cases.
- Isolated Broadway smoke suite: 18 passed. Backup collectors and other external
  actions are stubbed for widget tests; no real desktop windows are launched.
- Ruff lint/format, Pyright error checks, and diff whitespace checks passed.
- Service tests include real supervised worker cases as well as deterministic
  checks for hash/canonical validation, traversal/link/special-file rejection,
  stable-read changes, listing budgets, foreign/missing current output, binary
  rejection, comparison direction/counts/equality, and diff-size limits.
- UI tests cover normal/recovery navigation, literal metadata and diff rendering,
  neutral equality wording, stale-list disabling, clearing previous diffs,
  one-worker scheduling, cancellation, late callbacks, and process-exit cleanup.
- Existing Pending Changes diff behavior remains covered after adding a public
  precomputed-diff renderer for Backups.

### Real configured-directory observation

The actual supervised listing worker reported `unavailable` with zero candidates
because the configured Attune state/backup directory was absent. It returned
descriptive notes and did not create that directory. No fake backups were seeded
in the user's real state directory.

### Remaining work and limits

- Manual Wayland acceptance of the Backups layout is not established by the
  isolated Broadway suite.
- Backup validity means hash plus canonical format, not semantic or live safety.
  Hash-addressed files and mtime cannot establish chronological save history.
- Input, directory, and rendered-diff limits can omit candidates or truncate
  output; the interface reports those conditions rather than claiming equality.
- M2.3-M2.6 restoration drafts, reviewed writes, live application, and foreign-file
  preservation/replacement are not implemented. M0 mutating acceptance remains
  pending. This slice performs no restoration, deletion, or compositor operations.

## M2.3-M2.4: validated restoration drafts and reviewed disk writes

This later checkpoint supersedes the restoration-draft/write portion of the
previous slice's remaining-work list. M2.5-M2.6 and M0 acceptance remain pending.

### Automated coverage

- Full suite: 1,588 passed, 27 skipped. Twenty-six skips are opt-in GTK cases.
- Isolated Broadway smoke suite: 26 passed. Restoration APIs are mocked in widget
  tests; backend writes use temporary HOME/XDG fixtures, never live output.
- Ruff lint/format, Pyright error checks, and diff whitespace checks passed.
- Backend tests cover canonical/hash/scope/syntax validation, complete review
  binding, missing validators, unsafe targets, source/root/output changes before
  and under lock, rollback collisions, Stow preservation, cancellation, finite
  lock waits, reverse restoration, no-op behavior, and filesystem failures.
- Replacement-related uncertainty and post-replacement cleanup/cancellation are
  distinguished from definite pre-replacement failure. Recovery-cache regressions
  verify new editor construction sees restored disk values after success/uncertainty.
- UI tests cover read-only preparation and Cancel, frozen exact review, dirty and
  monitor blockers, direct non-daemon writer, close veto, one-use drafts, no-op
  unlock, success/uncertainty editor invalidation, and guarded save/edit/undo paths.

### Safety scope and outstanding acceptance

- No real user configuration was restored and no live compositor application or
  reload was requested. Actual Wayland restoration behavior remains unverified.
- Compile-only validation and canonical ownership are not full compositor semantic
  validation. Both current and proposed output must be existing nonempty owned data.
- A watched file may be auto-reloaded by Hyprland after a user chooses restoration;
  the absence of an explicit Attune reload command is not a no-live-change guarantee.
- Direct commit intentionally cannot be killed by the read-only worker timeout.
  Operation-level lock/validator bounds are not a hard total filesystem deadline.
- Foreign/missing/invalid-output recovery remains refused. No general overwrite
  exception, restoration CLI, automatic live application, or deletion was added.

## Checkout relocation

- Moved the complete checkout, including Git history and uncommitted work, to
  `~/Projects/attune`. The lowercase `~/projects` contained no other entries and
  was removed with an empty-directory operation, not recursive deletion.
- Preserved the former generated environment at
  `/tmp/opencode/attune-relocation.OJXHQW/.venv`, then rebuilt `.venv` with locked
  dependencies at the new path. Refreshed the already-installed local launcher.
- Both the checkout and `~/.local/bin/attune` launchers passed `--help`; the latter
  uses `~/Projects/attune/.venv/bin/python`. Usage documentation uses the new case.
- Before continuing development: 1,588 tests passed, 27 skipped, plus lint/format
  and type-error checks. The lowercase directory remained absent afterward.

## M2.6: preservation-first text recovery

This checkpoint supersedes the prior foreign/invalid-text recovery limitation.
Missing, empty, binary, oversized, and unsafe targets remain refused.

### Automated coverage

- Full suite at the relocated checkout: 1,708 passed, 35 skipped.
- Isolated Broadway smoke: 32 passed, 2 skipped. The two excluded combinations
  are recovery no-ops, which do not apply to replacement of non-owned text.
  Recovery/restoration writers are mocked in widgets and use temporary HOME/XDG
  storage in backend tests; no real user output is replaced.
- Ruff lint/format, Pyright error checks, and whitespace checks passed.
- Tests cover exact private-byte preservation, permission/ownership/link guards,
  file/directory synchronization before replacement, stale paths/roots/source,
  preservation/validator failures, cancellation, lock deadlines, cache invalidation,
  uncertain outcomes, and continued refusal by ordinary save/restore paths.
- Widget tests cover distinct recovery opt-in, acknowledgment, Cancel without
  writing, complete frozen reviews, writer close veto, and restart-required state.
- Normal-save regressions inject failures before replacement and after replacement
  during directory synchronization. Possibly-written outcomes invalidate cache,
  lock the editor, and block an identical retry; definite failures remain editable.

### Remaining limitations

- No live configuration recovery, Wayland UI acceptance, or compositor mutation
  was performed. M0 and explicit live application remain pending.
- The original foreign/invalid text is never compiled/executed. Only the canonical
  candidate is compile-checked; private `.bin` evidence is for manual inspection,
  not a guarantee of safe executable rollback.
- Ordinary saves/restoration remain ownership-restricted. No generic override,
  automatic fallback to recovery, or mutating recovery subprocess was added.
- Watched-file auto-reload, filesystem stalls, abrupt process termination, and
  hostile races are not eliminated by these application-level safeguards.

## M3.1: shared/local architecture decision

- Recorded [ADR 0001](decisions/0001-shared-local-ownership.md) after source inspection
  and an independent architecture review of ownership, transactions, and migration.
- Resolved design gaps around intervening v1 saves before handoff, distinct absent
  and empty migration priors, restart precedence while the registry is absent,
  and registry publication without an activation checkpoint.
- Loader/cache/watcher behavior remains explicitly unverified. Inherited helper
  comments and serializer output are not compositor-source or live acceptance proof.
- This checkpoint changes documentation only. No v2 implementation, configuration
  registry, journal, output migration, loader change, or live check was performed.
  The application suite was not rerun for the documentation-only slice; prior
  implementation results remain separate evidence, not validation of this design.

## M3.2: inactive scoped models, registry declarations, and v2 codec

### Verification

- Full suite: 1,997 passed, 35 skipped.
- Isolated Broadway smoke: 32 passed, 2 inapplicable recovery-no-op cases skipped.
- Ruff lint/format, Pyright error checks, and whitespace checks passed. Existing
  GI/dependency warnings remain distinct from passing type-error checks.
- Frozen combined/empty v1 fixture bytes and declared hashes are read unchanged
  by current persistence and backup validation. Expected fixture bytes are literal,
  not regenerated by tests. Explicit partition returns both scopes and preserves
  disabled/disconnected monitor order without changing the source.
- Scope tests cover closed fields, wrong types, forbidden empty cross-scope fields,
  deep immutability, stable independent content IDs, full byte hashes, exact
  regeneration, malformed/duplicate/deep/oversized records, and body/hash tampering.
- Registry tests cover exact fields, layout, normalized bounded absolute paths,
  declared overlap, nesting/UTF-8 limits, exact raw source identity, immutable
  constructors, and guarded absence of filesystem/environment/subprocess actions.
- Existing active v1 APIs continue refusing v2. No GUI/startup paths import or
  activate the new split model/registry parser.

### Limits

- Registry declarations, including `approved_resolved_path`, are not filesystem
  approval or write authority. Symlink/hardlink resolution, ownership, protected
  targets, and Git policy still require M3.3.
- No registry file, split output, journal, migration, loader, or live IPC action
  was installed. Rendered Lua was not loaded into a live compositor.
- V1 remains the only active write format; M0/runtime rollout gates remain pending.

## M3.3a: read-only filesystem route evidence

### Verification

- Full suite: 2,118 passed, 35 skipped.
- Isolated Broadway smoke: 32 passed, 2 inapplicable recovery-no-op cases skipped.
- Ruff lint/format, Pyright error checks, and whitespace checks passed. Existing
  GI/dependency warnings remain separate from type-error validation.
- Tests cover correctly scoped canonical pairs, registry permissions, output and
  parent ownership/modes, regular/single-link checks, Stow file/parent links,
  actual-versus-declared resolution, and symlink depth/hop bounds.
- Alias cases cover main/legacy/registry files and lexical/resolved state trees,
  including collisions through symlinked protected roots. Protected byte reads
  are refused, and main Lua is never parsed or executed.
- Registry/display Git placement covers `.git` directories, worktree-style files,
  and uncertain markers. Appearance Git placement is allowed. Revalidation catches
  new markers, registry whitespace/content changes, same-byte retargeting, parent
  replacement, permission changes, and newly present protected context.
- Independent review found a lexical-resolution permission gap. A kernel-followed
  metadata check now rejects a symlink route containing an unsearchable directory
  canceled by `..`. Both inspection/revalidation regressions ran as a non-root user;
  their directory permissions are restored during cleanup. They skip under root.
- Real isolated worker cases cover inspection/revalidation, missing context without
  creation, timeout/cancellation, and bounded strict evidence transport.

### Limits

- This is M3.3's inspection foundation, not complete scope-aware backup/diagnostic
  integration. Those adapters and the journaled writer remain pending.
- Only temporary fixtures were inspected for this slice. No live installation was
  provisioned, approved for writing, activated, or migrated; no GUI feature changed.
- Evidence is a transient non-atomic observation, not an authentication token,
  durable authorization, Lua/runtime validation, or permission to omit later checks.
- Ancestor `.git` markers are the supported Git boundary; arbitrary Git environment
  discovery is not implemented. Direct filesystem calls have no hard latency bound.
- No files/directories are written, created, chmodded, or repaired by inspection;
  ordinary filesystem access may update atime. Active v1 persistence is unchanged.

## M3.3b: scoped review, backup metadata, and diagnostics adapters

### Verification

- Full suite: 2,239 passed, 35 skipped.
- Isolated Broadway smoke: 32 passed, 2 inapplicable recovery-no-op cases skipped.
- Ruff lint/format, Pyright error checks, whitespace checks, and focused safety
  review passed. Existing GI/dependency warnings remain separate evidence.
- Review tests cover appearance-only/display-only/both/no-op proposals, exact
  unchanged-scope preservation, fixed bindings, immutable complete diffs, limits,
  stale route context, read races, and forged hashes/counts/paths/change sets.
- Backup tests use frozen literal v1 fixtures and both v2 scopes, preserving
  full-bundle classification and refusing hash/scope mismatch or implicit conversion.
- Diagnostic tests cover fresh revalidation, stale/path/permission changes,
  immutable observations, normalized time, and projection privacy against injected
  raw titles/errors/paths/hashes/values and malformed count/status metadata.
- Forbidden-effects tests confirm no writes, compilation, IPC, activation, or
  active-v1 behavior changes. Only temporary fixtures were read by these adapters.

### Limits

- M3.3's inactive core adapters are complete, not the split writer or GUI routing.
  No registry, journal, backup blob, split output, migration, or loader was created.
- Reviews and descriptor hashes are not commit permits, authentication, atomic
  snapshots, Lua semantic validation, or proof that output was loaded.
- Direct I/O/diff APIs have no hard wall-time bound. Future clients must supervise
  them off GTK; this slice adds no worker or public CLI for the adapters.
- Pure reports describe recorded collection-time evidence. Rendering alone cannot
  establish current freshness. Counts/timestamps may still identify activity.

## M3.4a: private evidence/journal records and interruption classification

### Verification

- Final full suite: 2,459 passed, 35 skipped.
- Isolated Broadway smoke: 32 passed, 2 inapplicable recovery-no-op cases skipped.
- Ruff lint/format, Pyright error checks, whitespace checks, and focused source
  safety review passed. Existing GI/dependency warnings remain distinct.
- Private-store tests cover exact ownership/modes, link/Git guards, immutable
  collisions, missing/corrupt evidence, incomplete predecessors, finite/cancellable
  locking, write-free no-ops, initialization-before-review, and every preparation
  fsync boundary. Intent publication follows verified synchronized evidence.
- Historical record tests reject malformed schemas/types, duplicates, excess depth
  or size, altered scope bytes/IDs/diffs/counts/bindings, and migration absence/empty
  priors. Recorded-review validation remains pure; fresh revalidation remains strict.
- Classification tests simulate every prior/proposed mixture and single-scope
  change, advisory phase/progress disagreement, safe changed-leaf replacement,
  unchanged-leaf drift, stale registry/links/parents/Git/protected paths, damaged
  private evidence, and mutation between observations. Actual bytes determine state.
- Tests compare scope bytes/inode/mtime/mode before and after private preparation
  and read-only classification. No production output-publication path exists here.

### Full-suite integration correction

An initial whole-suite run exposed order-dependent fixture registration in the
new transaction tests. Shared fixtures are now explicitly imported rather than
registering a collected test module as a plugin. Restrictive-permission tests now
restore original modes in `finally`; permissions on leftover generated fixtures
from earlier runs were restored so pytest could clean its own temporary trees.
The final full-suite run passed without those cleanup warnings.

### Limits

- Evidence initialization/preparation writes only when explicitly invoked. All
  such calls in this slice used temporary test state, never the live user's state.
- Only present-owned ordinary split saves are modeled. Migration absence/empty
  states, output publication, checkpoint advancement, resume/rollback, and startup
  or UI integration remain unimplemented.
- Prepared records establish verified private canonical evidence, not Lua compile
  validation, semantic safety, write authority, or successful publication.
- Classification is a direct, read-only, non-atomic observation, with no hard
  filesystem/diff wall-time bound. It cannot establish loaded runtime state.
- Failures can leave orphan/partial evidence and block preparation; nothing
  automatically repairs, deletes, resumes, rolls back, or activates anything.

## M3.4b: inactive guarded publication and reviewed recovery

This checkpoint supersedes M3.4a's publication/checkpoint/recovery limitations,
not its historical full-suite count. Application routing remains v1-only.

### Verification status

- Final full suite: **2,717 passed, 35 skipped**, completed in about 227 seconds.
- Focused publication + store tests: **336 passed** (about 198 seconds).
- Isolated GTK smoke: **32 passed, 2 skipped** (inapplicable recovery
  no-ops). These are isolated widget results, not live Wayland acceptance.
- Ruff lint/format, Pyright error checks, and whitespace checks passed. Existing
  GI/dependency warnings remain distinct from passing type-error checks.
- The initial full-suite runner's 120-second timeout was a runner deadline, not
  a recorded test failure. The longer-deadline full-suite rerun completed above.

### Coverage and protocol evidence

- Publication tests cover all current/desired compile checks before staging or
  replacement, missing/invalid/timed-out validators, and compiler-independent
  all-prior abandon after failed preflight. All-proposed finalize is metadata-only
  but still compile-checks. Terminal transactions cannot be replayed.
- Failure injection covers fsync calls and atomic checkpoint staging/replacement
  boundaries, output staging/replacement/sync, progress and terminal recording.
  Scope and journal uncertainty are independently sticky, including failure after
  a rename. Stale source, registry, private bytes/identity/mode, parent, Git,
  protected paths, forged reviews, lock timeout, and cancellation are covered.
- Real `os._exit`/SIGKILL cases stop after the first forward output replacement
  before checkpointing, during forward checkpoint scratch synchronization, after
  the first reverse restoration, and during reverse checkpoint scratch sync.
  Fresh parent-side loading/classification and reviewed resume/rollback complete
  only remaining changes despite old valid checkpoints, orphan staging files,
  and known mixed states, including non-prefix actual progress.
- Rollback tests cover direction locking, immutable initial restore scope selection,
  missing first checkpoint, partial reversal, and explicit same-action completion
  after reverse completion but before parent ABORTED. Already-goal and unchanged
  sibling bytes/inode/mtime/mode remain untouched; file/parent Stow links survive.
- Store regressions accept only recognized safe bounded unpublished checkpoint
  scratch as non-authoritative artifacts. Unknown/unsafe entries conflict. A fresh
  writer's scratch collision fails even for identical bytes and preserves the
  preexisting name, inode, bytes, and mode; it is not reused, promoted, or deleted.

### Safety boundary and remaining gates

All backend test outputs and private state are exclusively temporary. No live
mode, registry, loader, GUI Save/startup/CLI integration, migration, v1 reader
change, compositor reload, or user-state mutation was performed for this slice.
The new core mutators do write scopes when explicitly invoked; they are not
read-only. Separate renames are not pair-atomic and watchers may auto-reload even
without reload IPC. Filesystem reads/fsync may affect atime.

At this historical checkpoint, M3.6 scope-aware recovery/frontend/cache exclusion
integration was next, before M3.5 opt-in migration. Mutating callers must use direct non-daemon workers
and invalidate editors on scope changes/uncertainty without marking old baselines
Saved. Five-second locks and ten-second validator limits are not a hard filesystem
total deadline. M0 live acceptance, M2.5 live application, loader/watch validation,
and explicit rollout permission remain pending. Nothing auto-repairs, resumes,
rolls back, deletes evidence, or activates split routing.

## M3.6a: transaction recovery frontend and legacy exclusion

### Overview and verification status

Completed and validated as of 2026-10-30:

- Ruff lint with fixes and formatting: passed.
- Pyright over `hyprmod/` and `tests/`: zero errors. The unfiltered run reports
  162 `reportMissingModuleSource` warnings for dynamically supplied GI modules.
- Full suite, including publication fault/process-death coverage: **2,810 passed,
  53 skipped**. The opt-in GTK cases are skipped without an isolated display.
- Isolated Broadway widget suites: **50 passed, 2 skipped**, with compositor IPC
  disabled and service mutators mocked. The two skips are recovery/no-op combinations
  that cannot occur. The temporary Broadway daemon was stopped afterward.
- Independent backend and frontend safety review completed. Diagnostic markup
  handling was corrected; error paths and toast copy payloads are covered literally.
- Wheel build and installed launcher's `--help`: passed. The wheel was written
  under `/tmp/opencode/attune-m36a-dist`; nothing was installed or registered.
- No live Hyprland UI, user-state publication/recovery, migration, loader edit, or
  compositor mutation was performed. GTK checks are not manual live acceptance.

Dependency deprecation warnings remain for PyGI/GLib, Gio desktop APIs, Python
asyncio policy APIs, and GTK help overlays; they did not fail the checks.

### API / Interfaces and coverage to exercise

- `tests/test_scoped_recovery.py`: read-only assessment/preparation, strict immutable
  DTO round trips, complete both-scope reviews, actual-byte versus advisory-phase
  classification, corrupt evidence, terminal history without registry, row/scan
  limits, stale/forged drafts, context echo, cancellation/timeouts, and direct
  non-daemon commit with independent backend flags. No mutating child CLI exists.
- `tests/test_layout_guard.py`: metadata-only exclusion without registry/Lua byte
  reads, absent layouts without creation, safe empty transaction directories,
  registry files/directories/dangling links/FIFOs, nonempty or unsafe journals,
  symlink ancestors, and invalid context. Legacy backup/preserved archives alone
  do not imply a scoped installation.
- `tests/test_startup_layout.py`: assessment off GTK before editor construction,
  coalesced activation, non-clear/error fail-closed shell routing, cancellation and
  stale callbacks, retry veto during writes, and owner-aware recovery exclusion.
- `tests/test_scope_recovery_gui.py`: opt-in isolated Broadway coverage of explicit
  complete review without implicit commit, preparation refusal, writer lifetime
  and close veto, independent uncertainty invalidation, repeat recovery, permission
  rechecks, cancellation/late callbacks, discovery retaining pending edits, and
  failed reassessment locking the legacy editor and revoking stale rows/reviews.
  Services are mocked and compositor IPC disabled; these are not live recovery tests.
- Existing persistence/restoration/preservation regression suites remain required
  alongside these tests. Save, restoration, and preservation commits cover registry
  and journal exclusion at entry, under lock, and immediately before replacement,
  with unchanged destination/evidence and clean output-uncertainty flags on refusal.

### Data Flow and example validation commands

Run from the checkout using the isolated HOME/XDG test fixtures:

```bash
uv run ruff check hyprmod/ tests/
uv run ruff format --check hyprmod/ tests/
uv run pyright hyprmod/ tests/
uv run pytest tests/test_scoped_recovery.py tests/test_layout_guard.py tests/test_startup_layout.py -v
uv run pytest tests/ -v
```

With a separately started isolated `gtk4-broadwayd :8`, run:

```bash
ATTUNE_GUI_SMOKE=1 GDK_BACKEND=broadway BROADWAY_DISPLAY=:8 GSK_RENDERER=cairo \
  uv run pytest tests/test_scope_recovery_gui.py tests/test_gui_smoke.py -v
```

Stop the isolated daemon afterward. Do not launch a live compositor UI or commit
recovery against user state without explicit permission. See CONTRIBUTING for
the full self-review gate and local lint/format fixing commands.

### Edge Cases and remaining gates

Only `legacy-clear` admits editor construction. Scoped/blocked/error results stay
in recovery; any registry or transaction evidence, even terminal history, excludes
v1 save/restoration/preservation. Uninspectable metadata fails closed. Assessment
and review are bounded read-only child work; commits are direct non-daemon workers
with close veto and owner-aware exclusion. Either independent scope or journal
uncertainty invalidates cache/editor without marking old baselines saved.

No split editing, split publication through Save, registry activation, migration,
or scope-local v2 backup restore/preservation is completed by this slice. M3.6b
backup restore/preservation is next and a prerequisite before M3.5. M0 live
acceptance, M2.5 live application, loader/watch validation, and M3.5 migration and
rollout gates remain pending. No reload IPC does not prevent watcher auto-reload;
separate renames are not pair-atomic. Hashes/compilation prove neither runtime
loading nor Lua semantics, and operation bounds are not a total filesystem deadline.

### Related files

- `hyprmod/core/scoped_recovery.py`, `hyprmod/core/layout_guard.py`.
- `hyprmod/pages/scope_recovery.py`, `hyprmod/main.py`, `hyprmod/window.py`.
- [architecture.md](architecture.md#m36a-transaction-recovery-frontend-and-legacy-exclusion),
  [ADR 0001](decisions/0001-shared-local-ownership.md), and [ROADMAP.md](../ROADMAP.md).
