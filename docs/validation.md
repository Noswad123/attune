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
