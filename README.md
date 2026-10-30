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

Bindings, workspaces, layouts, rules, autostart, environment, plugins, and other
hand-authored behavior stay outside the GUI. There are no profiles or profile CLI,
automatic saves, startup reloads, main Lua parsing, configuration migrations, or
automatic include insertion in the focused application. Launching does not silently
register a desktop entry.

**First milestone: one `attune.lua` containing both monitor and appearance overrides.**
A shared-appearance/machine-specific-monitor split is not an active application mode.
Its accepted design is recorded in
[ADR 0001](docs/decisions/0001-shared-local-ownership.md); the proposed two-file
layout and registry activation are not available through the application.
Pure scoped models, registry parsing, and a v2 codec exist as development
foundations, not a split editing or installation mode.
An inactive read-only inspector can now verify explicitly supplied routes and
revalidate captured evidence. It does not discover, create, approve for writing,
or activate an installation, and is not a new GUI/launcher command.
Inactive adapters also prepare exact scoped review plans, describe v1/v2 backup
metadata, and project scoped diagnostics. The separate M3.4 backend
provides guarded split publication and explicitly reviewed resume, rollback,
finalize, and abandon operations. These core APIs write scopes/private journals
when explicitly invoked; they are not read-only. M3.6a now exposes only explicit
transaction recovery through the GUI and read-only assessment at startup. Split
editing, split publication through Save, CLI mutation, registry activation,
migration, and v2 editor routing remain unavailable.

### Roadmap

See [ROADMAP.md](ROADMAP.md) for the phased backlog and acceptance criteria:
validate the foundation, add diagnostics and recovery, separate shared/local
settings, then introduce constrained presets, Wisp entry points, and a CARAMEL
appearance overview. M1 diagnostics and M2 disk inspection/restoration/recovery
are implemented. Shared/local ownership design and pure scoped model/codec work
are complete, along with read-only route inspection and scoped review/backup/
diagnostic adapters and the M3.4 journaled publication/recovery backend. M3.6a
transaction recovery and legacy exclusion are completed in code. M3.6b scope-local
v2 backup restoration/preservation is next, before M3.5 opt-in migration. Explicit live
application and routing rollout remain gated by manual acceptance.
Unchecked roadmap items are not yet available features.

## API / Interfaces

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

Startup first shows **Checking Attune Layout**. Its bounded, read-only assessment
creates or repairs no state. Only `legacy-clear` permits construction of the v1
editor. Scoped evidence, blocked observations, and assessment errors open the
recovery shell with **Scope Recovery**, **Legacy Backups (v1)**, **Open Health**,
and **Retry Startup Check** instead. This does not select a runtime loader.

In Scope Recovery, refresh the assessment, choose a transaction and **Review
resume**, **Review rollback**, **Review finalize**, or **Review abandon**. The
backend refuses actions incompatible with actual bytes, locked rollback direction,
or terminal/conflicting evidence. Inspect the complete **CURRENT -> GOAL** review
for both appearance and displays, including unchanged scopes, paths, hashes,
content IDs, and review/private-evidence identities. Only the separate **Commit
Reviewed Scope Recovery** action writes. Canceling assessment/review writes nothing.

Assessment and review preparation use isolated, cancellable read-only children
with default deadlines of 15 and 30 seconds. Assessment shows at most 32 transaction
rows; truncation blocks legacy entry. Commits run directly on non-daemon workers,
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
they are not implicitly converted or restored into a v2 scope. M3.6b scope-local v2
backup restore/preservation remains pending before migration. Separate renames are
not pair-atomic; no reload IPC is sent, but watchers may auto-reload changed files.

### Output contract

The GUI's fixed default output is `$XDG_CONFIG_HOME/hypr/attune.lua`, falling back
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

1. Startup assesses layout off GTK before constructing an editor. Only a clear
   legacy layout proceeds to reading v1 managed data and sampling live options.
   Other results open recovery. No main Lua parsing or compositor reload occurs.
2. Interactive edits can immediately change compositor state via IPC, without
   writing any config file. Undo/discard operate on captured session baselines.
3. **Ctrl+S opens Pending Changes**, not a disk write. Review the exact diff,
   including previously managed values that will be emitted.
4. Choose **Save Reviewed Changes**. The save rechecks the draft, saved bytes,
   and resolved destination, validates ownership and Lua syntax, backs up previous
   nonempty content, and atomically replaces the resolved file.
5. Only a successful write updates UI save baselines. Persistent loading remains
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
- A changed draft, disk file, or resolved symlink destination invalidates the
  review. Review again rather than expecting a stale snapshot to save.
- Lua validation is **compile-only** (`luac -p`, or `lua -E` with `load`). It does
  not execute the generated chunk and is not full Hyprland semantic validation.
  A missing validator, syntax failure, or backup failure prevents replacement.
- Advisory locking and destination/content rechecks reduce accidental stale
  writes; they do not guarantee safety against hostile filesystem races.
- If ownership checks reject a file, preserve it and inspect it outside Attune.
  Do not strip the checks or paste hand-authored Lua into a generated file.

## Example usage

### First reviewed save, then manual integration

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

- [ADR 0001](docs/decisions/0001-shared-local-ownership.md): accepted ownership,
  transaction, loader, and migration design, with inactive implementation status.
- `hyprmod/core/transaction_publication.py`: explicit split writer and
  reviewed recovery backend; only recovery is integrated into the GUI.
- `hyprmod/core/scoped_recovery.py`, `hyprmod/core/layout_guard.py`,
  `hyprmod/pages/scope_recovery.py`: startup assessment, v1 exclusion, and explicit
  transaction recovery, separate from pending scope-local backup restoration.
- [ROADMAP.md](ROADMAP.md): priorities, milestones, and acceptance criteria.
- [CONTRIBUTING.md](CONTRIBUTING.md): development commands and verification policy.
- [docs/architecture.md](docs/architecture.md): current interfaces and persistence boundary.
- [docs/validation.md](docs/validation.md): verification evidence and outstanding live acceptance.
- `hyprmod/core/focused_ui.py`: supported pages/options and review snapshot type.
- `hyprmod/core/persistence.py`: canonical reader, validation, backups, atomic save.
- `hyprmod/window.py`, `hyprmod/pages/pending.py`: review and save orchestration.
- `hyprmod/main.py`: public entrypoint; internal module names are retained.
