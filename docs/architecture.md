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
A shared/machine-specific split is future work, not an implemented routing layer.
The selected future design is
[ADR 0001](decisions/0001-shared-local-ownership.md). It chooses two explicitly
registered scope outputs and journaled recovery, with manual loader handoff and
no claim of pair-atomic or runtime snapshot loading. The interfaces below remain
the shipped single-output implementation.

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

## Data Flow

1. **Startup:** the window warms the managed cache using the restricted reader,
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
