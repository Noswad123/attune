# Attune
![Attune](img/attune.jpeg)

## Overview

Attune is a personal, focused GTK4/libadwaita appearance editor for
[Hyprland](https://hyprland.org), forked from
[BlueManCZ/hyprmod](https://github.com/BlueManCZ/hyprmod) at `b475087`.
It previews supported changes through compositor IPC and writes compositor
configuration only after review.
The internal Python namespace remains `hyprmod` intentionally; the public launch
command is `attune`.

This fork retains the upstream attribution, including Copyright (C) 2026
Ivo Šmerek, and the **GPL-3.0-or-later** license. See [LICENSE](LICENSE).
Historical upstream releases remain in [CHANGELOG.md](CHANGELOG.md).

### Current scope

- General visual options: inner/outer gaps, border size, active/inactive border colors.
- Decoration, animations, and bezier curves.
- Monitor configuration with live preview confirmation.
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

Bindings, workspaces, layouts, rules, autostart, environment, plugins, and other
hand-authored behavior stay outside the GUI. There are no profiles or profile CLI,
automatic saves, startup reloads, main Lua parsing, configuration migrations, or
automatic include insertion in the focused application. Launching does not silently
register a desktop entry.

**Existing registered canonical-pair editing is implemented and validated.**
The normal editor can read, edit, review, Save, and continue editing
an already registered v2 appearance/display pair through the mature journaled
writer. The `legacy-clear` v1 `attune.lua` workflow remains unchanged.
This is not installation or migration: the app creates no registry, initializes no
store, provisions no missing/empty scope target, and edits no loader lines.
See [ADR 0001](docs/decisions/0001-shared-local-ownership.md).

### Roadmap

Next priorities are practical manual acceptance of the current app/pair workflow
and a reviewed, canonical-only opt-in migration. Automatic scoped foreign-file
preservation is **deferred and nonblocking**, not a prerequisite for either feature.
Diagnostics, explicit transaction recovery, and canonical historical restore are
already implemented; they are support features, not an open-ended recovery-foundation
milestone. M0 live acceptance remains pending, requiring separate user confirmation.
See [ROADMAP.md](ROADMAP.md) and the short [manual checklist](docs/validation.md#manual-acceptance-checklist).

## API / Interfaces

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

**Save Reviewed Changes** publishes exactly that review on a direct non-daemon
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
2. Interactive edits can immediately change compositor state via IPC, without
   writing any config file. Undo/discard operate on captured session baselines.
3. **Ctrl+S opens Pending Changes**, not a disk write. Review the exact diff,
   including previously managed values that will be emitted.
4. Choose **Save Reviewed Changes**. Legacy save rechecks the draft, saved bytes,
   and resolved destination, validates ownership and Lua syntax, backs up previous
   nonempty content, and atomically replaces the resolved file.
5. Pair Save uses journaled group publication and fresh exact post-save verification
   before updating baselines. Only verified success enables continued editing.
   Persistent loading remains
   an explicit configuration decision described below.

## Edge Cases

- **Live preview is not persistence.** Unsaved edits can still alter the desktop.
  Saving does not itself force a compositor reload; do not equate the saved file
  with the current runtime state.
- **Removing an override:** the preview uses the schema default, not your
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

### Edit an existing registered pair

Launch with the existing registry, canonical scopes, and safe initialized store.
Change an appearance value, press Ctrl+S, inspect **both** scope reviews (displays
should be unchanged), then choose **Save Reviewed Changes**. After verified success,
make another edit and repeat Save, then reopen to inspect persisted values. This is
the implemented and validated workflow, not authorization to run it on live state.
No provisioning or loader change is part of this example.

### Legacy first reviewed save, then manual integration

1. Launch from the checkout, adjust a supported visual option, press Ctrl+S,
   inspect the diff, and select **Save Reviewed Changes**.
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

These are instructions only. No entrypoint/include edits or live UI verification
against the desktop were performed. Isolated GTK smoke tests cover startup, page
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
