# Attune validation record

This records evidence, not a blanket claim of workstation acceptance. State-changing
M0 checks in [ROADMAP.md](../ROADMAP.md) remain pending explicit manual acceptance.

## Current status

### Bluetooth manager handoff: validated offline

The approved narrow addition is **Devices -> Bluetooth -> Open Bluetooth Manager**.
It opens external Blueman only on explicit activation, with missing-PATH guidance,
immediate spawn-error feedback and retry. No embedded/native Bluetooth controls,
package installation, service control, BlueZ access or new save unit were added.

Validation used the existing project `.venv` on Python 3.14.8. `uv` was unavailable
on PATH and the previously documented temporary uv executable was absent, so the
equivalent installed tools were invoked directly:

- `.venv/bin/ruff check --fix hyprmod/ tests/`: passed.
- `.venv/bin/ruff format hyprmod/ tests/`: 223 files unchanged.
- `.venv/bin/pyright --pythonpath /home/jdawson/Projects/attune/.venv/bin/python hyprmod/ tests/`:
  zero errors, 205 GI missing-module-source warnings. The initial invocation without
  explicit interpreter selection failed dependency resolution; the command above
  corrected the environment rather than suppressing diagnostics.
- Absolute `.venv/bin/python -m pytest tests/ -v`: **4,713 passed, 563 skipped,
  126 warnings in 800.01 seconds**. An earlier 600-second attempt timed out around
  89% and is not counted as a pass; the complete rerun used a longer bound.
- Five opt-in Broadway suites (`test_bluetooth_page_gui.py`, `test_gui_smoke.py`,
  `test_pair_editor_gui.py`, `test_cursor_page_gui.py`, `test_cursor_workflow_gui.py`):
  **140 passed, 2 skipped, 2,431 warnings in 69.88 seconds**. The skips are existing
  unchanged/restoration combinations. Warnings include GI/Python asyncio and GTK
  deprecations, not a warning-free result.
- Focused navigation/policy tests: **44 passed, 1 warning in 0.51 seconds**.
- Self-review, independent read-only diff review and `git diff --check`: no material
  findings or whitespace errors.

Process HOME, XDG_CONFIG_HOME, XDG_STATE_HOME and XDG_CACHE_HOME were prepared under
`/tmp/opencode/attune-bluetooth-validation` and set before Python started. Tests
retained per-test isolation. GTK used localhost-only Broadway with Cairo rendering;
test daemons were stopped after use. GUI compositor IPC stayed disabled and Bluetooth
executable lookup/spawning was mocked. The tests cover explicit launch, missing
executable, literal error text, retry, paths containing spaces, sidebar navigation,
editor-lock independence and preservation of existing draft/undo state.

`blueman-manager` was not found on PATH in this environment. No real manager was
launched, package installed, service controlled, or device discovered/paired/connected.
Live Hyprland UI presentation and Bluetooth behavior remain unverified. These results
do not close the broader Cursor final-validation checklist below or establish live
Input/Cursor acceptance.

### Cursor: implemented, final validation pending

#### Overview

The user accepted the Input checkpoint with "so far so good". After Cursor was
proposed next, "continue" approved that narrow work. This is not proof that live
Input output was loaded or actual devices verified. Cursor code is implemented;
final validation results are pending. No current pass/skip totals or completion
claim is made. The Devices-only **4,632/483** full and **480/2** GUI results below
are historical, not validation of the Cursor extension. Rules, startup and
environment remain later, separately scoped work.

#### API / Interfaces

The closed Input allowlist is 23 keys: Devices retains 15 keys/14 widgets and Cursor
adds eight native keys/eight widgets. Exact types, ranges and defaults are in the
[shared Cursor contract](architecture.md#cursor-shared-input-view). These were
checked against `hyprland-schema` 0.7.1's bundled Hyprland v0.56.1 catalog and the
matching [upstream source](https://raw.githubusercontent.com/hyprwm/Hyprland/v0.56.1/src/config/values/ConfigValues.cpp),
not every running version. Zoom/timeout now use `PreciseFloatOptionRow` entries:
explicit Apply, locale-aware round-trip display and decimal-arithmetic 0.1 +/−
buttons that apply. There is no one-decimal restriction or GTK spin rounding/
epsilon. Backend floats remain finite/bounded without a grid restriction; public
library emission proof may reject unrepresentable precision rather than rewrite it.
Other float spin rows are unchanged.

#### Data Flow

One `InputPage` owns Devices and Cursor, including one read-only observation,
draft/baseline, `_input_page` undo snapshots and dirty contribution. Separate
widgets/search/Pending navigation/badges do not create a fifth save unit.
**Save Reviewed Input** consumes the full combined review, invalidated by edits in
either view, and saves/adopts both together to `attune-input.lua` with the existing
lock/backups. Whole-unit Input Discard restores both. Uncertainty locks both views
as one unit, retaining the other three units' drafts/baselines/undo.

#### Final checks awaiting results

| Evidence to record | Status |
| --- | --- |
| Full-tree Ruff check/format and Pyright, including level/warning qualifications | Pending final results |
| Process HOME/XDG-isolated full pytest, exact counts/warnings/timing | Pending final results |
| IPC-disabled isolated GUI suites, including Cursor suites; exact results/isolation/cleanup | Pending final results |
| Backend/UI review findings and resolutions | Pending final results |
| Wheel, launcher help and diff checks | Pending final results |

Record actual outcomes here only when available, including failures, skipped or
unrun checks. Preserve process HOME/XDG isolation before Python starts, temporary
real publishers only, warning qualifications and effects limits. Source inspection
and existing test cases are not passing execution results. No live-loading/device
acceptance is established by this record.

Focused checks of decimal steps from defaults and saved fractional values through
real temporary reviewed Save were reported passing, without supplied totals here.
This is focused evidence only, not final-suite validation or live acceptance.

#### Edge Cases

Opening either view must create no overrides; Saved/Draft/Runtime/Default origins
must not imply actual device/loading proof. Devices-only canonical bytes remain
frozen under input v1, but older Attune rejects new Cursor keys, so this is not
downgrade compatibility. Theme/size/environment, `set_cursor`, GSettings and
hardware/render controls are excluded; the inherited theme picker stays inactive.
There is no preview/mutation IPC or automatic include/reload. A watched save can
nevertheless reload, so live-path writes/loading require separate explicit approval.

#### Example usage: limited manual checklist (pending)

Use prepared temporary HOME/XDG roots, an existing safe output parent and
IPC-disabled fixtures first. This checklist authorizes no watched/live writes.

1. In both admitted editor modes, open Devices and Cursor in either order. Check
   14 Devices widgets/15 keys and eight Cursor widgets/keys, origins, no overrides
   from opening and one observation. Search/Pending must navigate to the correct
   view; badges must not double-count Input dirty state.
2. Edit values in both views; exercise per-row Reset/Discard, shared Undo/Redo and
   whole-unit Input Discard. Preserve unapplied XKB text across Cursor edits.
   Check workspace warp integer choices and zoom/timeout locale-aware precision,
   explicit Apply and decimal 0.1 +/− steps through real temporary reviewed Save,
   starting from defaults and saved fractions. Unapplied numeric text must stay out
   of draft/review across unrelated edits/Undo/Redo; whole-unit Discard and saved
   adoption must refresh it authoritatively. Check bounds without mutation IPC.
   Backend finite in-range non-step floats remain admitted, subject to separate
   public library emission proof, with refusal rather than precision rewriting.
3. Inspect one full combined review, then edit in either view and confirm the old
   review cannot Save. Save Reviewed Input to temporary output, repeat and reopen;
   both views must adopt the verified baseline and clear only shared Input undo.
   Other units' saves must preserve the combined draft/baseline/undo and vice versa.
4. With temporary fixtures, exercise stale/foreign/unknown output refusal,
   Stow/existing-parent safety, writer exclusion/close veto and uncertain publication
   or failed adoption: retain drafts, lock both views, leave other units intact.
5. Check manual `dofile` guidance uses the actual absolute path only after output
   exists. Any later live load/device check needs explicit approval and a safe
   rollback plan; record version, actual effects and untested cases separately.

#### Related files

`hyprmod/core/input.py`, `hyprmod/pages/input.py`, `hyprmod/pages/pending.py`,
`hyprmod/window.py`, `hyprmod/ui/options/numeric.py`; `tests/test_cursor_input.py`,
`tests/test_cursor_page_gui.py`, `tests/test_cursor_workflow_gui.py` and the existing
Input persistence/page/workflow regressions. These are coverage locations, not
reported final results.

### Device/Input: validated offline, user acceptance pending

**Historical Devices-only checkpoint.** At this checkpoint user acceptance was
pending; the user subsequently accepted it and approved Cursor work as recorded
above. Live loading/device verification remains unproven and requires explicit
permission. The following final results retain their original Devices-only scope,
warnings and isolation qualifications, not current Cursor validation. Earlier
source/bindings/pair counts below remain historical; user-key runtime acceptance
is a separate outstanding check.

#### Final validation

| Check | Actual final result |
| --- | --- |
| Process-isolated `pytest tests/ -q` | **4,632 passed, 483 skipped, 106 warnings, 787.92 seconds (13:07)** |
| Eight isolated Broadway suites | **480 passed, 2 skipped, 9,159 warnings, 233.94 seconds (3:53)** |
| Ruff check `--fix` / formatter | Passed; formatter **218 files unchanged** |
| Pyright `--level error` | **0 errors, 0 warnings, 0 informations** in that level-filtered output; upgrade-version notice |
| `uv build --wheel` | Passed: `dist/attune-0.5.0-py3-none-any.whl` |
| `attune --help` | Passed |
| `git diff --check` | Passed, including after documentation updates |
| Independent backend/UI review | **No remaining material findings; P2s resolved** |

The eight suites were `test_gui_smoke.py`, `test_scope_recovery_gui.py`,
`test_pair_editor_gui.py`, `test_managed_bindings_gui.py`,
`test_keybindings_workflow_gui.py`, `test_source_bindings_gui.py`,
`test_input_page_gui.py` and `test_input_workflow_gui.py`, all under `tests/`.
Broadway ran on **`:12`**, stopped by the cleanup trap. The full suite and GUI suites
used temporary process `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME`
**before Python started**, including HOME
`/tmp/opencode/attune-bindings-validation-home`, with memory GSettings. The sentinel
`/tmp/opencode/attune-bindings-validation-home/.config/hypr/attune.lua` was verified
unchanged after the full suite. GUI compositor IPC was disabled, mutators mocked
by default, and explicit real publishers used temporary fixtures only.

Pyright's zero-warning output is at `--level error`, **not clearance of suppressed
warning levels**; the upgrade-version notice is retained as a qualification.
The pytest/Broadway warning totals above are not claimed clear.

No live input writes, loading, reload or IPC mutation occurred. No staging or commits
were performed. **Live-file hashes were not remeasured in this run**: historical
hashes later in this record are not current verification.

#### Resolved P2s

- **Sequential independent saves:** baselines separate exact own-source/Git proof
  from explicit `protected` evidence. A new review may refresh only safe known
  sibling-output regular/absent leaf proofs. Own bytes/config/proof and Git context,
  lexical/resolved paths, symlinks/ancestors, main/bridge/registry and Source's
  `installed_route` remain strict. Writers require full exact reviewed evidence
  under lock and at final checks: a post-review change invalidates Save, never
  silently rebases the reviewed publication. UI keeps original baseline identity,
  proposal/revision/draft/undo and adopts only its own verified result.
  **24 real-publisher GUI cases passed**, covering all **12 ordered unit pairs in both legacy
  and pair modes**, each saving all four units. Focused backend checks: **684 passed**.
  Source TSV's change includes narrow `same_source` matching in addition to shared
  safety-helper imports and the protected input filename, not just import changes.
- **Keyboard options and origins:** unapplied text survives unrelated edits without
  bypassing or losing Apply. Visible per-row origins distinguish Saved override,
  Draft override, Current runtime snapshot and Default, not observed. Unapplied text
  is explicitly labeled **Unapplied text (not in draft)** with the model origin;
  only applied values enter review. Owned values still take precedence over hints.

#### Overview

Devices exposes draft-only Keyboard, Mouse and Touchpad in both admitted legacy and
pair editors: 15 keys in 14 rows, with paired keyboard layouts/variants. Raw
`kb_options` preserves syntactically admitted unknown tags. Mouse and touchpad
scroll factors are conservatively 0.1–2.0 in 0.1 steps, not an unverified 10.
There is no live input preview. Touchpad disable-while-typing is not device disable.
Profiles/window layouts, per-device hardware matching, global device-disable and
keymap-file editing are excluded. Existing source UI/blank-row guidance is unchanged.

#### API / Interfaces

`core/input.py` owns the closed typed `InputConfig`/baseline/review/result and dedicated
`attune-input.lua` format. `core/owned_output.py` immediately shares only bindings/
Input fixed-output safety; Pending/window share review/writer mechanics, not a
generic framework. Source retains its separate writer with safety-helper imports,
protected-name updates and narrow `same_source` matching for new reviews. Visual
v1/v2, `Scope`, registry and journals stay unchanged. See the
[Input contract](architecture.md#devices--input) for exact keys.

#### Data Flow

Owned-file values are preferred. Unmanaged values show labeled read-only runtime
hints or fallback defaults, not proven device state. Opening creates no overrides.
Edit/Reset/Discard/Undo remain local, with layout/variant changes paired in one Undo.
Ctrl+S prepares the complete bounded Input review; only **Save Reviewed Input**
starts the direct non-daemon writer with global owner exclusion and close veto.
Dedicated `input.lock` and private hash-named `input-backups` stay outside Git.
Verified success adopts only Input; saving any of four units preserves all others'
drafts, baselines and undo. Uncertain Input locks only Input and retains other units.

#### Edge Cases

Keep regression checks in temporary output/state with process HOME/XDG isolation
before Python starts. Real publishers belong only in explicit temporary fixtures;
GTK checks disable compositor IPC and mock runtime hints/mutators. Existing-parent/
Stow safety, foreign/unknown refusal, stale reviewed evidence, backup/compiler
failures, repeat saves, writer exclusion, close veto and unit-local uncertainty are
offline contracts, not live hardware/loading proof. Output may resolve to Linux
Git/Stow but stays separate machine-side data; user controls commits and Attune never
stages. State/backups stay outside Git. See the final results and P2 coverage above.

#### Example usage: limited manual acceptance (not yet run)

Use prepared temporary roots, an existing safe output parent and IPC-disabled
fixtures first. Do not run against watched/user files without explicit approval.

1. In both admitted legacy and pair editors, open Devices. Check Keyboard/Mouse/
   Touchpad, 14 rows/15 keys, search/Pending navigation, clear **no input preview**
   wording and labeled unavailable/incomplete hint/default fallback. Opening alone
   must leave Input clean, with owned values preferred over different runtime hints.
   Inspect visible per-row Saved/Draft/Runtime/Default origins. Leave keyboard-options
   text unapplied, edit another row, then Apply: text must survive and be labeled
   not in draft until applied, without loss or accidental inclusion in review.
2. Change layout/variant together; exercise Reset, Discard, Pending Revert and one
   Undo/Redo for the pair. Try raw admitted unknown XKB options. Exercise numlock,
   repeat, mouse and touchpad rows without input mutation IPC. Check both scroll
   factors reject values outside 0.1–2.0 or off the 0.1 step.
3. Leave drafts in Input, source, additional bindings and visuals. Inspect the full
   Input-only diff, exact lexical/resolved paths and hashes. Edit again and confirm
   review invalidation. Save Reviewed Input to temporary output, repeat edit/review/
   Save and reopen. Confirm typed values and override removals persist. Repeat each
   other unit's Save and check all unsaved units' drafts, baselines and undo survive.
4. In temporary fixtures, check safe existing Stow links and resolved Git output,
   missing-parent refusal, foreign/manually edited/unknown data, stale bytes/routes,
   missing validator and backup failure. Exercise close veto/owner exclusion and
   uncertain Input outcomes: retain the draft, lock Input only, do not clear others.
5. Inspect Settings/review guidance: manual `dofile` must use the actual absolute
   path, **only after output exists**. No automatic include/loader/reload or live
   mutation. A watched write may nevertheless reload; saved is not loaded.

**Separate future load check, explicit permission required:** after user review and
approval of a safe loading/rollback plan, manually integrate the existing output
after authored defaults using its actual absolute path. Deliberately load and check
supported options, configuration errors and actual keyboard/mouse/touchpad behavior;
record hardware, unavailable settings and watcher observations. Do not infer any of
these from compile-only syntax checks or offline saves. No such check is claimed here.

#### Related files

`hyprmod/core/input.py`, `hyprmod/core/owned_output.py`, `hyprmod/core/bindings.py`,
`hyprmod/pages/input.py`, `hyprmod/pages/pending.py`, `hyprmod/pages/settings.py`,
`hyprmod/window.py`; `tests/test_input_persistence.py`, `tests/test_input_page.py`,
`tests/test_input_page_gui.py`, `tests/test_input_workflow_gui.py`. Final parent
evidence, warning/isolation qualifications and effects limits are recorded above.

### Source shortcut UI correction: earlier validated checkpoint

**UI correction: implemented and validated in code and isolated GTK tests.** The unified
**Keybindings** list retains all 80 rows in stable order. Every pencil opens
**Edit Source Shortcut**; there is no Delete button, Assign New or Unassigned expander.
On the actual installed default `/home/jdawson/.config/hypr/keybindings.tsv` (not
Prepared), use pencil -> clear **Shortcut** -> **Update Pending** ->
**Review Source Shortcuts...** -> **Save Reviewed Source Shortcuts**. The same row
stays blank after Save/restart and its edit dialog opens empty. Pending says
**Clear shortcut**, not Delete; Disable retains the assigned key off.
Backend/state/schema and installed unassignment capability are unchanged: no
deployment is needed. Reassigning through the empty field defaults Enabled on once
a key is entered. This docs-only pass ran no commands or tests; the following are
the supplied final parent results, not newly executed checks.

### UI-only correction: final validation

- Full-tree Ruff `check --fix` and format passed: **210 files unchanged**.
  Full-tree Pyright `--level error`: **zero errors**, not GI-warning clearance.
- Full pytest: **4,361 passed, 383 skipped, 12 dependency warnings, 763.64 seconds**.
  Temporary process HOME/XDG isolation was set **before Python started**.
- All six parent Broadway suites: **380 passed, 2 skipped, 6,315 dependency warnings,
  129.00 seconds**. IPC disabled; writers mocked by default, explicit real publishers
  used temporary fixtures only; daemon stopped.
- Earlier agent checks: source GUI **84 passed**; source regressions **333 passed**.
  Quick source-only independent review: **READY, no material bugs**.
- Wheel `/tmp/opencode/attune-empty-shortcuts-dist`, installed launcher help and
  `git diff --check` passed. Sandbox sentinel unchanged.
- Changes were confined to source-page GUI code/tests: stable 80-row list, identical
  edit pencils, blank Save/reopen without moving the row, Enabled-on default for a
  new assignment, separate key-retaining Disable and Clear shortcut pending title.
  No backend/format/bridge/main/dotfiles/data/dependency changes or deployment.
- Real-file hashes were verified unchanged: main `c20f1af0...`, bridge `1d1023aa...`,
  TSV `7a6d5d61...` (full hashes remain in the deployment record below). All live
  mappings were preserved. No live UI/runtime shortcut callback tests, IPC, reload,
  live source Save, staging or commits occurred. Live acceptance remains unverified.

Former Delete/Assign New UI descriptions and validation/deployment checkpoints below
remain historical, not current instructions or replacements for these results.

The earlier Delete/unassignment fix was **implemented and validated in code and isolated tests**. The
user-approved Delete-capable bridge-only deployment completed on **2026-11-03 UTC**;
installed helper `1d1023aa...` supports both `disabled-v1` and `unassigned-v1`.
That historical checkpoint's full pytest: **4,361 passed, 383 skipped**; all six Broadway
suites: **380 passed, 2 skipped**. These were not rerun for that deployment, which left
app code unchanged; the later UI-only validation is recorded above.
Main Lua and mappings remain unchanged, all 80 assigned/enabled including Super+T.
The installed helper already supports the current clear-field workflow without
deployment. Live unassignment behavior remains unverified.

Earlier source editing, including reversible disable, was **implemented and validated in
code** through automated and isolated GTK checks. Results below record the supplied
validation run; this documentation pass did not rerun it. The user-approved compatible
bridge-only update completed on 2026-11-03 UTC, preserving main Lua and TSV.
The on-disk capability guard passes; disabled-key runtime behavior is not yet tested.
The user-approved three-file source integration was **deployed on 2026-11-02**;
read-only runtime inspection observed all 80 expected descriptions with unchanged
keys, flags and native contexts and zero config errors. Live shortcut **behavior
remains user-untested**; M0 is not blanket complete. Device/Input's offline checkpoint
has since been accepted by the user; Cursor final validation is pending as recorded
at the top, without live loading/device proof. Additional managed bindings retain their
earlier automated/isolated GTK checkpoint, not new live loading/capture acceptance.
Profiles/layout pages remain out of scope.

### Source shortcut Delete versus Disable: implemented and validated

Historical pre-UI-correction checkpoint, followed by the 2026-11-03 UTC deployment
record. Its former Delete/Assign New workflow is superseded by Current status above;
the results and receipts are preserved, not new validation or current UI instructions.

#### Overview

The user clarified that Delete must remove the assignment, not merely turn it off.
At that checkpoint the backend, page and candidate bridge implemented this distinction.
Historical disable-only counts below did not validate that later fix.
Its own final automated and isolated-widget results are recorded below, as supplied
by the final validation report, not newly executed by this documentation pass.

#### API / Interfaces

`SourceBinding.assigned` is `key != ""`; `enabled` is assigned and not `disabled`.
The current contract is:

| State / action | Saved key value | Metadata flag | Persisted state with compatible bridge |
| --- | --- | --- | --- |
| Enabled | Nonempty | No `disabled` | Assigned and enabled |
| Disable | Nonempty key retained, off | `disabled` | Assigned and disabled after normal restart; Pending Modified |
| Delete / clear field | Exactly empty, old key value removed entirely | No `disabled` | Unassigned after normal restart; Pending Removed |

Unassigned is exactly empty key with no `disabled`; empty+disabled is invalid.
Delete or blank-field clearing removes the old key value from the saved mapping,
not an old-combo/off tombstone. Disable retains its assigned key. All 80 catalog
declarations remain, with immutable ID/context/native submap/base flags/order and
unchanged descriptions unless edited. Authored callbacks remain at their original
sites; no action deletion, main-Lua rewrite or Lua evaluation is added.

#### Data Flow

The former Assigned shortcuts (N) counted assigned keys, including disabled ones, excluding
unassigned records. These moved into collapsed Unassigned actions; Assign New started
empty, not from an old/default combo. Pending Delete is Removed, assignment Added,
Disable/Enable Modified. Undo/Redo/Discard/Revert preserve all three states.
Both Delete and Disable persist through the independent source review/Save path.

The candidate has ordered capability lines:

```lua
-- Attune source bindings capabilities: disabled-v1
-- Attune source bindings capabilities: unassigned-v1
```

Any unassigned proposal requires both markers on the selected companion and relevant
actual installed companion under the existing alias guard. Review and direct backend
commit block unsupported helpers before state/data writes, with a clear update message
naming `disabled-v1 and unassigned-v1`. Disabled-only proposals need only `disabled-v1`.
Metadata/route binding and existing proof rechecks remain unchanged: selected and
known installed companion alias/route evidence is checked before state creation,
under lock and immediately before replacement.

#### Edge Cases

Existing valid assigned data, disabled format and v1 schema are unchanged. Valid saved
data with a compatible bridge preserves disabled/unassigned state on reopen and repeated
configuration load without default resurrection. Missing/broken helper or invalid
catalog still selects whole defaults. This is not an unconditional guarantee under
file corruption. The bridge must consume all 80 declarations, not emit 80 bindings:
unassigned/disabled rows skip `hl.bind`, without forwarding `disabled` as an option.

The previous helper, SHA-256 `0fc1fa9f6b7351e13ef140ad62ab2a4f4832cc64af73e08c942e25e7c2fa88a8`,
was **disable-only** and restores defaults for empty-key data. It has now been replaced
by the compatible helper recorded below. No mapping deletion has occurred.

#### Example usage

At this historical checkpoint, the intended workflow was: close/reopen Attune, open
Keybindings -> Existing shortcuts and confirm the installed default TSV (not Prepared).
Find Open terminal (T) / `terminal.t`, choose **Delete shortcut** (not Disable), then
**Review Source Shortcuts...** -> **Save Reviewed Source Shortcuts**. No further
deployment approval is needed. These are user actions, not actions performed for them.
Delete removes the saved key value; expect 79 assigned shortcuts, one action in
Unassigned actions with blank-field Assign New, and 80 declarations. Disable instead
retains the key persistently off. Ctrl+S/visual Save is not source Save. Reload Hyprland
configuration if needed to apply the runtime deletion: the user chooses any manual
command, which can reset unsaved live previews. Watcher reload may happen immediately;
no reload IPC was sent. Live behavior acceptance remains pending.

#### Final automated and isolated-widget results

- Required full-tree Ruff `check --fix` and format: **passed, 210 files unchanged**.
- Full-tree Pyright `--level error`: **zero errors**. This is not a claim that
  unfiltered GI warnings are clear.
- **Final full pytest: 4,361 passed, 383 skipped, 12 dependency warnings, 783.67 seconds**.
  Process HOME and all XDG paths were temporary and set **before Python started**.
  This is the authoritative final run. An earlier non-prefixed full run reported the
  same pass/skip counts, **13 dependency warnings, 767.71 seconds**, then was rerun
  with the proper process environment. Do not describe all runs as process-isolated
  or infer that the earlier run established configuration writes.
- All **six** isolated Broadway GUI suites: **380 passed, 2 skipped, 6,332 dependency
  warnings, 138.21 seconds**. Temporary process HOME/XDG was set before Python;
  writers were mocked by default, with actual publishers only against temporary
  outputs/state/store. Compositor IPC was disabled and the daemon stopped afterward.
- Independent review: **no material findings**. Review-run backend/equivalence:
  **332 passed**; review-run source GUI: **82 passed**. These focused counts precede
  the post-review additions below, not substitutes for the final suites.
- Post-review focused additions: actual-disk mixed enabled/disabled/unassigned
  persist/reopen regression **1 passed**; actual Pending Delete -> key reuse ->
  Revert regression **2 cases passed**, both editor modes. Conflicting Revert refuses
  atomically without changing draft, baseline, history or disk. Both additions are
  included in the final full and applicable GUI suites above.
- Wheel `/tmp/opencode/attune-source-delete-dist`, staged candidate bridge `luac`
  parse, installed launcher help and diff check: **passed**. Staged candidate here
  means the validation copy, not a live installation or Git staging.
- Sandbox sentinel remained unchanged. No live source-data/bridge/key edits,
  installation, reloads, shortcut invocations, Git staging or commits occurred during
  this code-validation checkpoint, before the approved helper-only deployment below.
  This does not assert process isolation for the earlier non-prefixed run.

#### Approved Delete-capable bridge-only deployment

The user replied **“go ahead”** after an explicit request to install only the
Delete-capable helper, keeping main Lua and mappings unchanged. The supplied actual
deployment record is dated **2026-11-03 UTC**, not execution by this docs updater.

- Lexical target `/home/jdawson/.config/hypr/keybindings-bridge.lua` resolved to
  `/home/jdawson/.dotfiles/stow/linux/hyprland/.config/hypr/keybindings-bridge.lua`.
  The directory symlink was preserved. Only the helper was replaced by atomic rename,
  mode `0644`, from `0fc1fa9f6b7351e13ef140ad62ab2a4f4832cc64af73e08c942e25e7c2fa88a8`
  to `1d1023aa710cba8fa6a1732518da42bacf3668cbf1d3ab9a28a9028083da21a7`.
  Both ordered capability headers are present.
- Verified private evidence:
  `/home/jdawson/.local/state/attune-installations/source-bindings-delete-20261103T023850Z`
  (owned `0700` directory, `0600` files), containing `originalhelper.before`, reviewed
  new helper, main/TSV snapshots, manifest and activation receipt. Compile-only `luac`
  parse, readback hashes and backups passed verification.

Post-deployment SHA-256 values (main and TSV exactly match their snapshots):

| File | SHA-256 |
| --- | --- |
| `hyprland.lua` | `c20f1af019703ff92b2451de9f0443ea1e1dee37943f85d675d40724df8c5840` |
| `keybindings-bridge.lua` | `1d1023aa710cba8fa6a1732518da42bacf3668cbf1d3ab9a28a9028083da21a7` |
| `keybindings.tsv` | `7a6d5d6145ccb5c1a39be965541306b46da6b821b0a0f44d2fa58796f79db3d7` |

Mappings remain **80 declarations, 80 assigned, 80 enabled, zero disabled and zero
unassigned**, including actual Super+T. Public `source.observe` and `prepare_review`
accepted two separate **in-memory-only** `terminal.t` proposals: Delete with `key=""`
and no `disabled`, and Disable retaining Super+T with `disabled`. No `persist_reviewed`
call occurred; a fresh observation confirmed the unchanged TSV hash.

Read-only `hyprctl binds` / `configerrors` still showed **80 bindings, 80 descriptions**,
all exact expected catalog matches, no missing rows or nonblank errors. Keys/flags/native
submap metadata digest exactly matched baseline:
`1824fe84035e77f206ed9c8ee05047ba86c836a91bf3181700e381e972f6873c`.
This proves on-disk compatibility, not that the running process loaded the new helper
or that actual runtime Delete works: no mappings changed. The next full configuration
load uses the compatible on-disk helper. Watcher reload is possible, but no reload IPC
or callback invocation was sent. No user data was deleted/disabled, no main/mapping
installation occurred, and nothing was staged or committed. The preexisting untracked
`attune.lua` was left untouched. App code remains unchanged from the **4,361/383** full
and **380/2** GUI checkpoint; no fresh full rerun is claimed.

**Rollback:** the prior helper supports only `disabled-v1`, not empty keys. After user
deletion, do not blindly downgrade and resurrect defaults. Require fresh compatibility
review and user reassignment of unassigned actions, or a safe updated-helper plan.
Never restore a snapshot TSV over later edits. The older disable-only and original
three-file deployment records below remain history, not instructions to repeat them.

#### Related files and documentation-pass limit

The historical checkpoint inspected `core/source_bindings.py`, `pages/source_bindings.py`, candidate
`integrations/hyprland/jdawson/keybindings-bridge.lua`, and the three source-binding
test modules. Coverage then included Delete/blank fields, empty Assign New,
three-state pending/undo/revert, temporary Save/reopen, repeated compatible-bridge
declarations without resurrection, and disable-only installed-alias refusal.
The supplied final validation above passed. Tests were **not rerun** here. This docs-only pass
ran no shell/tests/app/IPC, changed no source/tests/live files, staged and committed
nothing. All historical counts, hashes and deployment receipts below remain history.

### Source shortcut disable fix: implemented and validated

Historical disable-only checkpoint, not validation of the later Delete fix. Descriptions
of pending removal/addition below record the prior UI semantics, now superseded above.

The reported inability to remove Super+T exposed the original key/description-only
scope. Source inspection now shows reversible row **Disable/Enable** and a dialog
**Enabled** switch. `SourceBinding.enabled` derives from metadata-only `disabled`
in the existing flags column. V1/schema and all-enabled bytes remain unchanged.
Catalog/IDs/context/submap/base flags/order and all 80 records remain intact, with
key/description and authored callback retained for restoration. Pending entries
distinguish disable/removal and enable/addition; Undo/Redo/Discard/Revert include
state. Disabled combos are available to another enabled source row; conflicting
re-enable refuses before mutation. The updated project bridge checks all 80 IDs
seen but skips `hl.bind` for disabled rows, never passing `disabled` as an option.

#### Automated results

- Full-tree Ruff `check --fix` and format: **passed, 210 files unchanged**.
- Full-tree Pyright `--level error`: **zero errors**. Unfiltered GI warnings remain;
  this is not an all-warnings-clear claim.
- Full pytest: **4,332 passed, 367 skipped, 13 dependency warnings**, **753.75 seconds**.
- All six isolated Broadway GUI suites: **364 passed, 2 skipped, 5,939 dependency
  warnings**, **111.22 seconds**. IPC disabled, writers mocked by default; explicitly
  real source, managed-bindings and pair publishers used temporary fixtures only.
  The Broadway daemon was stopped.
- Focused backend/equivalence: **304 passed**. Source GUI: **68 passed**, including
  Super+T disable in the source view, flags and complete review, temporary Save/reopen,
  re-enable, reuse of a disabled combo and atomic conflicting re-enable refusal.
- Wheel build at `/tmp/opencode/attune-source-disable-dist`, updated candidate bridge
  `luac -p`, installed launcher `--help` and diff check: **passed**.
- Process HOME/XDG isolation was set before Python started; the sentinel stayed
  unchanged. No watched files/user keys changed, no live Super+T disable, live bridge
  installation, reload, staging or commits occurred. Final read-only hashes are below.

These results validate code and isolated widgets, **not live disable behavior**.
The earlier key/description-only counts below remain historical.
This documentation pass ran no shell/tests/app/IPC and changed no code/tests/live
files, staged nothing and committed nothing.

#### Compatibility and resolved P1 finding

**Compatibility gate:** old all-enabled TSV is readable by old/new bridges. The
old bridge would reject `disabled` and restore **all 80 defaults**.
Review and commit therefore require the companion's first-line
`-- Attune source bindings capabilities: disabled-v1` and captured bridge path
proof whenever the proposal contains disabled rows. Missing/old helpers explicitly
block Save with "Update the source keybindings bridge before saving disabled
shortcuts; older bridges would restore defaults." Disable is not silently dropped.

**P1, direct-Stow bypass resolved:** a selected direct source TSV beside a new helper
could alias the actual installed TSV whose helper was still old. Checking only the
selected companion was insufficient. `SourceBaseline.installed_route` now captures
a metadata-only `PathProof` for the actual config root's `hypr/keybindings.tsv`,
including strict JSON transport validation. A shared resolved target or device/inode
requires **both selected and actual installed companions'** capability headers and
protected proofs. The installed TSV route and helper proofs are bound to the review
and rechecked before state creation, under lock and immediately before replacement.
Post-write verification permits only the writer's own selected regular-leaf identity
change, including the aliased installed route; all other route/bridge facts remain
bound. Unrelated offline TSV editing stays independent. No main Lua is read/evaluated.

Regression tests passed for old/missing actual helpers refusing direct writer calls
before state/data writes, both-new success, unrelated offline editing, symlink
retargeting and changed helpers invalidating stale evidence. Independent source-only
review confirmed P1 resolved with **no blockers**. This is a protective compatibility
guard, not a claim that old loaders understand new tokens or future formats.

#### User-approved bridge-only deployment and activation limit

The user replied **“continue”** after an explicit request to install only the compatible
bridge, preserving main Lua and TSV and not disabling Super+T. The supplied deployment
record reports completion on **2026-11-03 UTC**; this docs pass performed no deployment.

- Lexical target `/home/jdawson/.config/hypr/keybindings-bridge.lua` resolved to
  `/home/jdawson/.dotfiles/stow/linux/hyprland/.config/hypr/keybindings-bridge.lua`.
  Directory symlink `../.dotfiles/stow/linux/hyprland/.config/hypr` was preserved.
  Atomic rename replaced old SHA-256
  `33d7ced25ec1c403d1c0b59c5c60bace17eac324cf7ebfa0bace5507afe78504`
  with the new helper below, mode `0644`.
- Private evidence at
  `/home/jdawson/.local/state/attune-installations/source-bindings-disable-20261103T004642Z`
  (`0700` directory, `0600` files) contains `oldhelper.before`, `new.reviewed`,
  `main.snapshot`, `data.snapshot`, manifest and activation receipts. Targeted `luac`
  syntax validation, exact hashes and backup readback passed.

Post-deployment SHA-256 values (main and TSV unchanged):

| File | SHA-256 |
| --- | --- |
| `hyprland.lua` | `c20f1af019703ff92b2451de9f0443ea1e1dee37943f85d675d40724df8c5840` |
| `keybindings-bridge.lua` | `0fc1fa9f6b7351e13ef140ad62ab2a4f4832cc64af73e08c942e25e7c2fa88a8` |
| `keybindings.tsv` | `7a6d5d6145ccb5c1a39be965541306b46da6b821b0a0f44d2fa58796f79db3d7` |

All **80 rows remain enabled**, including `terminal.t`; Super+T was not disabled.
No main/data writes or live-keymap mutations were performed, no reload IPC was sent,
and no callbacks were invoked. Post-install read-only `source.observe` and
`prepare_review` with an **in-memory-only** `terminal.t` disabled proposal succeeded,
proposing only that ID. No persist call occurred; fresh `source.observe` confirmed
the TSV hash unchanged. Read-only `hyprctl` inspection still showed **80 bindings,
80 descriptions, zero nonblank config errors**, with exact before/after key/flag/native
context digest `1824fe84035e77f206ed9c8ee05047ba86c836a91bf3181700e381e972f6873c`.

This proves installed-helper compatibility and stable current metadata, **not runtime
disable behavior or that the running process loaded the new bridge**. It may retain
the old helper in memory until the next configuration parse. The installed helper
understands disabled rows on next load. At that deployment, source code was unchanged from the final
**4,332 passed / 367 skipped** checkpoint; no fresh full CI/suite rerun is claimed.

**Historical next action, superseded by the Delete sequence above:** restart Attune -> Keybindings -> Existing shortcuts, confirm
the **installed default TSV**, not Open Prepared Source Mappings. Find Open terminal
(T) / `terminal.t` -> Disable -> Review Source Shortcuts -> Save Reviewed Source
Shortcuts. Ctrl+S or visual Save alone is not source Save. After Save, removal takes
effect at the next Hyprland configuration load. Watcher reload remains unproven;
the user may manually reload if necessary. Attune does not force a reload, and
watched-file reload risk remains even without IPC.

**Rollback warning:** do not downgrade to the old helper while any rows are disabled:
it cannot parse that data and selects all 80 defaults. Require fresh compatibility
review and user re-enabling of all disabled rows, or another explicitly safe plan,
before any approved downgrade. Never restore snapshot TSV over later user edits.
The original three-file deployment below is history, not an instruction to repeat it.

### Existing source shortcuts: current evidence and limitations

The pre-deployment runtime observation was **80 bindings, all `__lua`, zero descriptions**.
It is an input observation, not a fresh query made by this docs pass. Numeric `arg`
values are Lua registry references, not callback text or source line numbers.
Runtime descriptions are preferred when supplied, but opaque references alone do
not make a useful editor for this inventory.

Source inspection confirms Existing shortcuts -> Open Prepared Source Mappings
selects the repository's offline `keybindings.tsv`. The UI can draft key/description
edits and independently review/save this explicitly selected metadata now, without
installing main/bridge/data. Enabled-state edits additionally require the compatible
companion described above. IDs, context, native submap, base flags, order and authored
callbacks remain fixed. Additional managed bindings and visuals save separately.
The final isolated source-widget coverage below validates that workflow, not live
loading or compositor behavior.

The reference refactor remains in `integrations/hyprland/jdawson`; installed copies
are now live through the existing Stow route, as recorded below.
The bundle README retains its earlier focused checkpoint separately from current
disable validation. `tests/test_source_bindings_equivalence.py` captures 80
registrations under isolated Lua stubs, compares original/default keys, flags,
native contexts and symbolic actions, checks callback source/upvalues and startup
snapshots, and checks reverse-mechanical restoration of the frozen original.
It does not invoke registered callbacks, real startup IO or compositor behavior.
Neither that sandbox nor compile-only checks prove live acceptance. The app never
executes authored main Lua.

#### Historical key/description-only automated results

- Full-tree Ruff `check --fix` and format: **passed, 210 files unchanged**.
- Full-tree Pyright `--level error`: **zero errors**. Unfiltered baseline GI warnings
  remain; this is not an all-warnings-clear claim.
- Full pytest: **4,291 passed, 343 skipped, 12 dependency warnings**, in
  **744.17 seconds**.
- All **six** isolated Broadway suites: **340 passed, 2 skipped, 5,498 dependency
  warnings**, in **91.35 seconds**: `tests/test_gui_smoke.py`,
  `tests/test_scope_recovery_gui.py`, `tests/test_pair_editor_gui.py`,
  `tests/test_managed_bindings_gui.py`, `tests/test_keybindings_workflow_gui.py`,
  and `tests/test_source_bindings_gui.py`. Compositor IPC was disabled; writers were
  mocked by default. Explicit real source, managed-bindings and pair publishers used
  **temporary files/state/store only**. The Broadway daemon was stopped.
- Focused equivalence: **114 passed**. Permanent custom key/description tests now
  parameterize **every one of the 80 IDs**, not only four examples. Coverage includes
  virtual mapping-read exceptions and helper syntax failure selecting defaults,
  the all-80 default symbolic registration trace and byte-for-byte reverse restoration
  of the original, including callback bodies. These are not live behavior proofs.
- Source-backend focus: **149 passed**.
- Wheel build passed at `/tmp/opencode/attune-source-bindings-dist`. Installed
  launcher help, internal `source_bindings` read-only observe/review CLI help and
  diff check passed. No mutator CLI or installation is implied by help/build checks.

#### Resolved review findings

- **P2, actual-config-root aliases:** `SourceBaseline.config_root` and immutable
  protected proofs now bind the actual seven main/generated/registry routes
  independently of selected/Stow source location, plus protected source-sibling
  routes. `observe` / `run_observe` accept optional keyword `config_root` with
  XDG/home default; the GUI and workers pass and check explicit context. Protected
  paths are metadata-only, never authored-Lua reads. Direct-alias and post-review
  race checks cover this protection.
- **P2, reload warning:** source UI/review now warns that saving an **already-integrated
  or watched TSV may trigger an immediate reload**, not only after some later
  integration. No reload IPC does not guarantee no runtime effect.
- **P2, pending navigation:** managed-binding Pending rows explicitly select the
  **Additional bindings** tab rather than landing on Existing shortcuts.

Independent rechecks found **no blockers**. These fixes preserve independent source,
managed-binding and visual save units, not a new main-Lua writer or unbinding path.

#### Final isolation and effects report

Process HOME/XDG paths were isolated **before Python started**, with per-test
temporary fixtures retained. The sentinel
`/tmp/opencode/attune-bindings-validation-home/.config/hypr/attune.lua` stayed
unchanged. Dotfiles were unchanged apart from the **preexisting** untracked empty
`/home/jdawson/.dotfiles/stow/linux/hyprland/.config/hypr/attune.lua` observation from
the prior run, left untouched; its origin remains unattributed. Do not describe
that tree as clean or attribute the file to this run. The historical observation
and isolation correction below remain part of the record.

During that historical automated validation, no live keymaps or authored main were written, no integration installed/reloaded,
no runtime callbacks invoked, and no activation, staging or commits performed.
Those effects describe the automated checkpoint, not the later approved deployment
below. Offline equivalence remains distinct from live shortcut behavior acceptance.
At that historical checkpoint, Device/Input was planned after keybinding acceptance.
Its offline checkpoint has since been accepted by the user and Cursor work approved,
with final Cursor validation pending as recorded at the top. Neither establishes
live loading/device proof; live shortcut acceptance remains separately pending.

This docs-only pass ran no shell, tests, app or compositor commands and changed no
source/tests. The results above record supplied validation, not new
execution by the documentation updater. Earlier counts below remain historical.

#### Source integration activation and rollback

**User-approved deployment completed on 2026-11-02.** The following is the supplied
actual deployment record, not execution by this documentation updater:

- Preflight: `HOME=/home/jdawson`, config root `/home/jdawson/.config`;
  `hypr` directory symlink `../.dotfiles/stow/linux/hyprland/.config/hypr`
  was preserved. Prior main SHA-256
  `f25db9b117b560a8e9ed8542be9a993be28f6990f45cdd59b9815101728c6fc4`
  matched the frozen fixture. Prior presence: main **present**, bridge **absent**,
  data **absent**.
- Private evidence: `/home/jdawson/.local/state/attune-installations/source-bindings-20261102T155506Z`
  (`0700` directories, `0600` files) contains `hyprland.lua.before`, reviewed
  candidate copies, `manifest.json` and `activation.json`. Retain the prior-absence
  fields for rollback; absent helpers have no prior bytes to restore.
- With watcher/reload risk explicitly accepted by the user before writing, installed
  bridge -> data -> **main last**, using individual atomic renames into actual Stow
  source files, mode `0644`. Installed SHA-256 values match the validated candidates:

  | File | SHA-256 |
  | --- | --- |
  | `hyprland.lua` | `c20f1af019703ff92b2451de9f0443ea1e1dee37943f85d675d40724df8c5840` |
  | `keybindings-bridge.lua` | `33d7ced25ec1c403d1c0b59c5c60bace17eac324cf7ebfa0bace5507afe78504` |
  | `keybindings.tsv` | `7a6d5d6145ccb5c1a39be965541306b46da6b821b0a0f44d2fa58796f79db3d7` |

  Config-root symlink routing stayed unchanged; unrelated `attune.lua` was untouched.
- Read-only `hyprctl binds` / `configerrors`: before **80 bindings, 0 descriptions,
  0 errors**; after **80 bindings, 80 descriptions, 0 errors**. All 80 descriptions
  exactly match the source catalog, with no missing/extra rows. Keys, flags and native
  contexts match exactly. Unchanged metadata hash:
  `1824fe84035e77f206ed9c8ee05047ba86c836a91bf3181700e381e972f6873c`,
  excluding `arg`, `description`, `has_description`; description-related Lua registry
  reference changes in `arg` are allowed. No explicit reload IPC, shortcut callback
  invocation or model-triggered key sequences were sent.
- App source-binding `observe` on the installed path succeeded with **80 rows**.
  Close/reopen Attune -> Keybindings -> Existing shortcuts to use the installed
  default `/home/jdawson/.config/hypr/keybindings.tsv`. Open Prepared Source Mappings
  is only for the separate reference/preview copy, not required for installed editing.
- User keys did not change: installed TSV exactly matches defaults. Callback bodies
  remain unchanged by the prior offline proof (**114 tests**), not by live action
  execution. Deployment validation used Lua syntax checks, hashes and read-only
  metadata. The full suite was **not rerun** because app code was unchanged; the
  4,291/343 and other automated counts above remain the last historical checkpoint,
  not fresh deployment CI. No staging, commits or automatic installer were added.

**Ordering and rollback safeguards remain applicable.** No rollback is recorded.
Any future live-path write needs explicit approval and a fresh check for intervening
changes. No reload IPC does not prevent watcher-driven reload. The retained manual
procedure is:

1. Obtain approval for the three-file manual installation and maintenance/session
   boundary, including watcher risk and recovery access. Review the offline main,
   bridge and complete TSV against the final validated checkpoint before proceeding.
   Recheck the live main against the frozen baseline; reconcile intervening user
   changes rather than overwriting them with a stale candidate.
2. Inspect lexical/resolved Stow routes for all three destinations. The candidate
   specifically expects `$HOME/.config/hypr/keybindings-bridge.lua` and that directory's
   `keybindings.tsv`; it does not discover arbitrary selected files or XDG overrides.
   Record existing/absent status, bytes, permissions and link routing for the main,
   bridge and data. Verify backups **outside all watched configuration/dotfiles
   paths** before any replacement; retain an accessible recovery session.
3. Manually install the reviewed trusted bridge first, reviewed TSV second, and
   candidate **main `hyprland.lua` last**, preserving intended Stow routing. Recheck
   the reviewed files before replacement. Main-last limits incomplete dependencies;
   it is not an atomic installation or guarantee against automatic reload.
4. With the approved activation method, inspect config errors, all 80 registrations,
   expected descriptions/keys/flags/native submaps, and actual shortcut behavior.
   Include terminal aliases, manager Lua-state gating, Wisp reset/actions,
   hardware keys and pointer bindings. Record dated pass/fail/untested results and
   Hyprland version. Missing/bad data should select all bridge defaults, not a mix;
   missing/unloadable bridge retains source defaults. Do not deliberately corrupt
   live files merely to exercise fallback tests.
5. If rollback is needed under the approved recovery plan, restore the prior **main
   first** to remove dependency on new helpers. Then restore prior bridge/data from
   backups, or remove only newly introduced files whose prior absence was recorded.
    Verify current routes/hashes against the deployment evidence before any rollback;
    do not overwrite or delete unknown later changes. Preserve original Stow routing.
    Re-establish loading through the approved session/
   reload method and verify errors and prior shortcuts. Keep backups until acceptance.
   Both rollback and installation may trigger watchers; neither is automatic app work.

**Current next step:** the bridge-only update above is installed, preserving TSV and
main Lua. Do not repeat the original three-file deployment. The user can now restart
Attune and explicitly Delete/review/save `terminal.t` against the installed default TSV,
as described in the ready-now workflow above. No further deployment approval gate remains.
Testing terminal aliases, Wisp and volume keys remains pending. Manager gating, other hardware/pointer
actions and remaining M0 checks still require explicit user acceptance. The project
bundle remains a reference, not a directory directly loaded by the live config.

### Managed keybindings: implemented and validated

#### Final automated results

- Full-tree Ruff `check --fix` and formatting: passed; **205 files unchanged**.
- Full-tree Pyright `--level error`: **zero errors**. Baseline unfiltered GI warnings
  remain; this is not an all-warnings-clear claim.
- Final full pytest: **4,026 passed, 299 skipped, 13 dependency warnings**, in
  **737.65 seconds**. Backend-focused run: **88 passed**.
- All five isolated Broadway suites: **296 passed, 2 skipped, 4,707 dependency
  warnings**, in **64.37 seconds**: `tests/test_gui_smoke.py`,
  `tests/test_scope_recovery_gui.py`, `tests/test_pair_editor_gui.py`,
  `tests/test_managed_bindings_gui.py`, `tests/test_keybindings_workflow_gui.py`.
  IPC was disabled. Writers were mocked by default; explicitly real publishers,
  including bindings and pair Save, ran only against temporary fixtures. The
  Broadway daemon was stopped.
- Wheel build passed: `/tmp/opencode/attune-keybindings-dist`. Installed launcher
  `--help`, internal read-only bindings worker help (observe/review modes), and diff
  check passed. No new mutator CLI or live keybinding application was added.
- The initial full run had one stale navigation-mock failure. `test_focused_window`
  was corrected to mock `ManagedBindingsPage`, positively check lazy bindings
  navigation, and check the actual unsupported profiles/layout condition. The final
  full suite above passed after that correction.

#### Validated coverage and review corrections

Automated/isolated coverage includes managed search/add/edit/delete, GTK-only draft
capture/manual fallback, read-only runtime/opaque rows and unknown origins, unknown
offline inventory, new/moved conflicts and same-combo local edits. It exercises
review invalidation, dirty baselines, Undo/Redo/Discard, deletion restoration,
repeated Save/reopen, and independent visual/bindings save units without false Saved
state or cross-unit undo loss. Temporary filesystem cases cover dedicated-format
absent/empty/owned targets, foreign/unknown refusal, protected aliases, existing
parents, Stow preservation, lock/private backups, failures and unit-local uncertainty.
First-save guidance requires manual `dofile` with the actual absolute path only
after output exists. These checks do not establish live capture or loading behavior.

- **P1, command emission:** the library migration emitter could rewrite `exec`
  `hyprctl` arguments and instance controls. Validation now rejects public
  `dispatch_to_lua` output unless its `exec_cmd`/`exec_raw` quoted argument decodes
  exactly to the original command. Actual generation still uses `keyword_to_lua`.
  Ordinary `$`, quotes, commas and operators remain supported when literal emission
  is proven. Rejected rewrites give actionable direct-action guidance; Raw command
  is suggested only if intended, not as a hand-translation workaround. Tests inspect
  actual emitted Lua bodies, not just metadata.
- **P2, backup root:** `.git` directories and worktree files at the backup root are
  checked before lock creation, under lock and through final verification.
- **P2, dialog arguments:** structured defaults/clamps now fall back to exact
  plaintext. Regressions preserve `dpms` argument `off HDMI-A-1`, `cyclenext` argument
  `prev`, resize values of `20000`, and arguments during shortcut-only edits.
  Draft-mode action lists hide submap.
- **P2, Revert:** owned-baseline Revert can restore the original saved combination
  despite opaque runtime overlap. Owned uniqueness is checked before mutation;
  expected `ValueError`s produce toast feedback.

Source-only independent rechecks confirmed all four original findings resolved.
This is not independent live semantic verification.

#### Validation isolation and unexplained file observation

During the initial full run, a new untracked empty legacy visual-v1 target was
noticed at `/home/jdawson/.dotfiles/stow/linux/hyprland/.config/hypr/attune.lua`.
Its origin is **not established**: static review could not attribute it to pytest
versus concurrent user activity. It was left **untouched**, without deletion or
repair. This record does not claim a clean user tree or that no file appeared.

Subsequent full-suite and GUI validation set process HOME/XDG paths **before Python
startup** under `/tmp/opencode/attune-bindings-validation-home`, in addition to
per-test fixtures. The sandbox `attune.lua` sentinel and the observed live file's
content remained unchanged. One test's broad `monkeypatch.undo()` was replaced with
a scoped context to avoid restoring global HOME isolation patches. Future full/GUI
runs must preserve both process-level and per-test isolation; see CONTRIBUTING.

No live app or compositor IPC tests were run. No loader lines were installed, no
user-configuration mutator was intentionally invoked, and nothing was staged or
committed. These limits do not establish the unexplained file's cause. This
documentation update ran no commands and changed no source/tests or live state.

#### Remaining manual acceptance

- [ ] With separate explicit permission, verify live shortcut behavior and GTK
  capture/manual fallback, without claiming reserved shortcuts reach GTK.
- [ ] Only after generated output exists, deliberately arrange manual `dofile`
  loading with its actual absolute path and inspect behavior/errors. Attune inserts
  no includes and sends no reload. Saved does not mean loaded; watcher behavior is
  still unverified.

### Earlier canonical-pair checkpoint

Existing registered canonical-pair normal edit/review/Save/continue is **implemented
and validated**. M0 and live pair/loader/watch acceptance remain pending separate
user confirmation. Automated and isolated widget results do not establish live
workstation integration.

### Historical pair-editor automated results

- Required `ruff check --fix` and formatting: passed; **199 files unchanged**.
- Full-tree Pyright with `--level error`: **zero errors**. Unfiltered baseline GI
  source-resolution warnings remain; this is not an all-warnings-clear claim.
- Full pytest suite: **3,907 passed, 231 skipped, 5 dependency warnings**, in
  **627.66 seconds**. Use a **1,200,000 ms** timeout for future full-suite runs.
- All three isolated Broadway suites (`test_gui_smoke.py`,
  `test_scope_recovery_gui.py`, `test_pair_editor_gui.py`): **228 passed, 2 skipped**,
  in **42.52 seconds**. Service/compositor IPC is disabled. Mutators are mocked by
  default; explicit pair-Save end-to-end cases use the **real publisher** exclusively
  against temporary outputs and private stores. The Broadway daemon was stopped.
- Wheel build: passed, output under `/tmp/opencode/attune-pair-editor-dist`.
  Installed launcher help, internal read-only `editor_layout` help for `entry` and
  `review`, and Git diff whitespace check: passed. Nothing was installed, staged,
  or committed.

No live app/UI, real user configuration/state writes, compositor operations, loader
edits, migration, or live registry creation/provisioning were performed. Test
installations, including their registry/store fixtures, were temporary only.

### Independent review and corrections

- Backend review found no material defects. UI review found no data-loss,
  stale-write, or cross-owner bugs.
- P2 stale-disk guidance was corrected: session-local edits do not survive restart;
  retry review only for temporary failures. If files/routes changed, manually
  correct or restore the registered canonical files/routes, then restart/reopen.
  The original pair baseline cannot adopt external edits.
- P3 contradictory Scope Recovery copy was corrected: explicit reviewed canonical
  historical restore is available; foreign preservation and migration remain absent.

Automatic scoped foreign preservation is deferred and nonblocking for canonical
editing or canonical-only opt-in migration. Missing/foreign/invalid scopes, missing
or unsafe storage, pending/corrupt evidence fail closed with explicit recovery or
manual remediation, never overwrite. No migration, registry creation, store
initialization, loader editing, or new public CLI is claimed.

### Validated coverage

- `tests/test_editor_layout.py`: existing-pair entry, zero journals, complete terminal
  scans beyond recovery display caps, pending/corrupt refusal, manual-remediation
  messages, immutable models, exact both-scope goals, isolated stdin transport,
  cancellation/deadlines, and unchanged legacy metadata-only entry.
- `tests/test_pair_editor_gui.py`: opt-in isolated normal pair startup without v1
  cache reads, dirty-only merges, temporary real repeated Saves/reopen, Stow/sibling
  preservation, both-scope edits, review invalidation, worker exclusion/close veto,
  clean failures, uncertainty and post-save verification failure retaining dirty state
  with **both independent sticky flags** set. Actual `MonitorState` edits through
  public monitor-page APIs pass real temporary review/Save/reopen while retaining
  disconnected records and unchanged appearance identity.
- `tests/test_health_input.py`: bounded stdin round trips, interleaved output,
  broken pipes, cancellation/deadlines, and pre-launch size refusal.
- Full-suite validation includes legacy persistence, restoration, recovery,
  transaction store/publication and startup regressions alongside this coverage.
  Preserve temporary HOME/XDG isolation in future runs; never provision live state
  merely to validate the feature.

## Manual acceptance checklist

**Instructions only. Do not execute without separate explicit user confirmation.**
Use a user-approved existing pair/store, preserve recovery material, and record
dated pass/fail/untested results, Hyprland version and hardware. Do not provision or
edit loader lines merely to satisfy this checklist.

- [ ] Launch the current app; confirm the expected legacy or existing-pair editor.
  In pair Settings, check registered/resolved routes and legacy-only Health/Backups
  labeling. File presence and matching drift do not prove runtime loading.
- [ ] Preview a scalar, Undo/Discard, then edit again. Ctrl+S must show complete
  both-scope review; an appearance-only edit must leave displays unchanged. Edit
  after review and confirm the old review cannot Save.
- [ ] Explicitly Save, verify the reviewed disk result and untouched sibling/Stow
  link, then make and Save a second edit without restart. Reopen and check values,
  untouched curves/animations and disconnected display records.
- [ ] With separate permission for display changes, exercise Keep/Revert/timeout
  and close veto during monitor preview; resolve it before Save. Record animation,
  scaling/topology and HDR acceptance or untested cases under M0.
- [ ] On approved disposable fixtures, check pending/corrupt history and damaged or
  missing scopes/store open recovery with useful instructions, never overwrite or
  initialize. Use a fresh explicit transaction review for pending work; preserve
  evidence and manually remediate other damage. Do not corrupt real user state.
- [ ] Record how the user's existing manual loader/reload setup makes saves effective,
  including override removal and observed errors. Save sends no reload IPC, but
  watchers may auto-reload. M0 is not passed until applicable live checks are recorded.

## Historical checkpoints

All results below retain their original counts and qualifications. Statements about
inactive routing or foreign preservation preceding migration describe the policy
at that checkpoint, not current prerequisites. They do not validate the new editor.

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
or scope-local v2 backup restore/preservation was completed by this historical slice.
Canonical restore and existing-pair Save were delivered later; automatic foreign
preservation is deferred and does not block canonical-only migration. M0 live
acceptance, M2.5 live application, loader/watch validation, and M3.5 migration and
rollout gates remain pending. No reload IPC does not prevent watcher auto-reload;
separate renames are not pair-atomic. Hashes/compilation prove neither runtime
loading nor Lua semantics, and operation bounds are not a total filesystem deadline.

### Related files

- `hyprmod/core/scoped_recovery.py`, `hyprmod/core/layout_guard.py`.
- `hyprmod/pages/scope_recovery.py`, `hyprmod/main.py`, `hyprmod/window.py`.
- [architecture.md](architecture.md#m36a-transaction-recovery-frontend-and-legacy-exclusion),
  [ADR 0001](decisions/0001-shared-local-ownership.md), and [ROADMAP.md](../ROADMAP.md).

## M3.6b1: read-only scoped restore preparation

### Overview and verification status

B1 is implemented and validated as of 2026-10-30. M3.6b remains In progress.

- Ruff lint with fixes and formatting: passed.
- Repository-wide Pyright error-level check: zero errors. Unfiltered GI source
  availability warnings remain as recorded at the M3.6a checkpoint.
- Full suite, including publication fault/process-death coverage: **2,943 passed,
  53 skipped**, in about 283 seconds.
- Isolated Broadway compatibility suites: **50 passed, 2 skipped**, with compositor
  IPC disabled and service mutators mocked. The daemon was stopped afterward.
- Wheel build, installed launcher help, internal read-only worker help, and diff
  whitespace checks: passed. The wheel is under `/tmp/opencode/attune-m36b1-dist`;
  nothing was installed, registered, staged, or committed.
- Independent safety review found no blockers. Follow-up tests cover actual later
  two-scope publications, same-ID unrelated journal corruption between scans,
  rehashed inconsistent historical snapshots, and nested draft immutability.
- No live UI, user-state restore/recovery, compositor operations, migration, or
  authored loader/config changes were performed. Publications in integration
  tests use temporary outputs/state only. No new GUI behavior is added by b1.

### API / Interfaces and coverage to exercise

- `tests/test_scoped_restore.py` exercises both scopes, prior/proposed selections,
  COMMITTED/ABORTED sources, complete CURRENT -> GOAL reviews retaining the current
  sibling, old sources after later terminal history, safe canonical leaf replacement,
  and mutation-free no-ops without creating a lock or evidence.
- Refusal/race cases cover missing initialized storage, damaged current selected or
  sibling output, exact registry/roots and both-route binding, unresolved/corrupt or
  oversized journal scans, source record/blob replacement, newly added terminal
  history, damaged unselected blobs, and current-review freshness.
- Draft/worker cases cover frozen strict nested semantics, rehashed forged goals,
  descriptors/diffs/counts, duplicate/unknown fields, invalid JSON/types, aggregate
  eight-MiB ASCII-escaped transport, pure decoding without filesystem access,
  isolated `-I -B` execution, exact context/selection echo, cancellation/timeouts,
  and malformed/oversized replies.
- Forbidden-effect tests guard writes, lock/store creation, compilation, main Lua
  reads, IPC, and persistence. `tests/test_transaction_store.py` separately covers
  `refuse_pending_readonly`, including terminal evidence verification without lock
  acquisition or provisioning.

### Data Flow and example validation

Using exclusively temporary HOME/XDG fixtures, exercise
`tests/test_scoped_restore.py` and `tests/test_transaction_store.py`, then the
existing scoped recovery, publication, legacy persistence/restoration/preservation
regressions and full CONTRIBUTING gate. No live source or store is needed. The API
sequence and bounds are in
[architecture.md](architecture.md#m36b1-read-only-scoped-restore-preparation).

### Edge Cases and remaining gates

Terminal phase/fingerprints are local observations, not authentication, proof that
either historical side was installed, or write permits. Preparation and pure draft
decoding do not authorize a later write. At the b1 checkpoint, source browsing/review
and writer source freshness under lock were next. Separate foreign preservation is
now deferred and nonblocking for canonical-only migration. B1 adds no source discovery/listing, frontend, commit API/CLI,
compiler, provisioning, foreign preservation, migration, or ownership exception.
M0 live acceptance and loader/watch rollout gates remain pending.

### Related files

- `hyprmod/core/scoped_restore.py`, `hyprmod/core/transaction_store.py`.
- `tests/test_scoped_restore.py`, `tests/test_transaction_store.py`.
- [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility)
  records why foreign originals cannot be admitted to canonical-only snapshots,
   reviews, or compiler paths as raw blobs.

## M3.6b2: historical source browsing and read-only review

### Overview and verification status

B2 is implemented and validated as of 2026-10-30. M3.6b remains In progress.

- Ruff lint with fixes and formatting: passed.
- Repository-wide Pyright error-level check: zero errors. Unfiltered GI source
  availability warnings remain as recorded at the M3.6a checkpoint.
- Full suite, including publication fault/process-death coverage: **3,039 passed,
  104 skipped**, in about 354 seconds. Most skips are opt-in isolated GTK cases.
- Isolated Broadway widget suites: **101 passed, 2 skipped**, with compositor IPC
  disabled and service mutators mocked. The temporary daemon was stopped afterward.
- Independent safety review and follow-up completed. Result-mode authority leakage
  and missing history-discovery editor notification were fixed, with boundary and
  editor/live-apply exclusion regressions. No blocking findings remain.
- Actual isolated listing-worker transport, wheel build, installed launcher help,
  internal worker help, and diff whitespace checks: passed. Build output is under
  `/tmp/opencode/attune-m36b2-dist`; nothing was installed, registered, staged, or
  committed by this task.
- Live Hyprland UI, user-state mutation/recovery, loader edits, reloads, and
  compositor operations were not performed. Widget checks are not live acceptance.

### API / Interfaces

`scoped_restore.list_sources` / `run_list` return strict immutable listing DTOs;
the internal worker explicitly selects `list` or `prepare`. Listing has a 1 MiB
transport cap; preparation retains the 8 MiB draft cap. Both supervised wrappers
default to 30-second deadlines. `ScopeRecoveryPage.browse_sources` requests history
explicitly; `prepare_source` selects a reviewable scope/side and shows a full
read-only CURRENT -> GOAL pair. Startup does not browse or provision history.

### Data Flow and coverage to exercise

- `tests/test_scoped_restore.py`: four sources per verified row, full 1,000-entry
  safety scan independent of the 32-row display cap, hidden pending/corrupt evidence,
  scan versus display flags, row-local historical route mismatch, old terminal
  sources after later publications, evidence races, strict immutable DTOs, transport
  limits, isolated worker modes/context echo, cancellation, and forbidden effects.
- `tests/test_scope_recovery_gui.py`: explicit browsing, full precomputed both-scope
  reviews and current sibling/no-op labels, recovery/history transitions, single
  async read slot through cancellation, closure/late callbacks, permission rechecks,
  wrong-mode/type/context/selection and partial-render refusals, historical evidence
  discovery locking while retaining dirty edits, and historical reviews never
  populating recovery drafts or invoking commit.
- Run these with temporary HOME/XDG fixtures alongside transaction-store, scoped
  recovery, publication, legacy persistence/restoration/preservation regressions,
  the full CONTRIBUTING gate, and isolated Broadway widget suites.

### Edge Cases

Display truncation does not mean incomplete scanning. Pending/corrupt evidence
globally blocks, including undisplayed journals; incompatible historical routes
block only their rows if globally safe. Old terminal recovery actual-conflict
classification is not historical source eligibility. Phase/hashes are not installed
proof, runtime/compiler validation, authentication, or write permits.

Historical review cannot enable the existing transaction recovery commit. No
historical restore writer, compilation, provisioning, foreign preservation, or
migration was added by b2. Under-lock source freshness and a new restore transaction
followed in b3; foreign preservation is deferred, not a migration prerequisite. No live UI,
user-state mutation, loader edit, reload, or compositor operation was performed;
M0/manual rollout gates remain pending.

### Example usage

For isolated widget validation, browse history, select an eligible prior/proposed
scope, inspect both complete reviews, and verify the recovery commit stays disabled.
Cancel and re-browse, then separately prepare a transaction recovery action to
exercise the existing commit path with mocked mutators only.

### Related files

- `hyprmod/core/scoped_restore.py`, `hyprmod/pages/scope_recovery.py`.
- `tests/test_scoped_restore.py`, `tests/test_scope_recovery_gui.py`.
- [architecture.md](architecture.md#m36b2-historical-source-browsing-and-read-only-review),
  [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility).

## M3.6b3: canonical backend restore commit

### Overview and verification status

Backend implemented and validated as of 2026-10-30. M3.6b remains incomplete.

- Ruff lint with fixes and formatting: passed.
- Repository-wide Pyright error-level check: zero errors. Unfiltered dynamic GI
  source-resolution warnings remain as recorded at the M3.6a checkpoint.
- Full suite, including restore and publication fault/process-death tests:
  **3,107 passed, 104 skipped**, in about 575 seconds. Allow a longer command timeout
  than the earlier 480-second budget for the expanded suite.
- Isolated Broadway compatibility suites: **101 passed, 2 skipped**, with compositor
  IPC disabled and service mutators mocked. The temporary daemon was stopped.
- Independent backend safety review found no blocking defects. Follow-up tests
  directly pin source-hook lock ownership for changed/no-op publication and reject
  mutable historical snapshot/descriptor containers before copying or delegation.
- Wheel build, installed launcher help, internal read-only worker help, and diff
  whitespace checks: passed. The wheel is under `/tmp/opencode/attune-m36b3-dist`;
  nothing was installed, registered, staged, or committed by this task.
- No live GUI, user-state restore/publication, loader edit, reload, or compositor
  mutation was performed. All write/crash tests use temporary outputs and state.
  At the b3 checkpoint, the historical GUI remained read-only; compatibility smoke
  tests are not live Hyprland acceptance.

### API / Interfaces

`scoped_restore.commit_restore(draft, cancel_event=...)` is an explicit direct
non-daemon backend mutator. It passes a validated private draft copy to ordinary
publication with an under-lock source hook and a new transaction ID, preserving
delegated result flags unchanged. Only read-only `list`/`prepare` have supervised
children (1 MiB/8 MiB transport); at this checkpoint there was no GUI historical
action. There is still no commit CLI.
Existing interruption recovery/`commit_recovery` behavior remains unchanged.

### Data Flow and coverage to exercise

The validated regression coverage includes:

- `tests/test_scoped_restore_commit.py`: both scopes/sides and COMMITTED/ABORTED
  sources; new transaction IDs, reverse restores, sibling/registry/source evidence
  isolation, lexical Stow links, and no-op journal/stage absence.
- Original exact types and nested immutable containers before JSON copying; forged
  roots/digests/diffs/goals, private-copy isolation from later original mutation,
  direct daemon refusal, pre-cancel, lock contention, and delegated flags/exceptions.
- Same-byte source intent/snapshot/selected and unselected blob replacement, current
  selected/sibling and registry drift; pending/corrupt evidence even for no-ops;
  compiler-time changes; source drift after preparation/sync/final stage read,
  rename, and terminal checkpoint. Generated-ID collisions, including allocation
  races and existing PREPARED entries, cannot replay that evidence.
- Compiler/rename/post-rename/fsync/checkpoint uncertainty followed by explicit
  existing recovery of the new transaction. The real crash test uses `os._exit(73)`
  after selected-output rename before progress checkpoint, then parent-side fresh
  review/finalize. It uses temporary outputs/state, not live user configuration;
  it is not a production timeout-killable mutator design.

Run alongside `tests/test_scoped_restore.py`, transaction publication/store and
scoped recovery tests, legacy persistence/restoration/preservation regressions,
the full CONTRIBUTING gate, and isolated GUI compatibility suites. All mutating
fixtures must remain exclusively temporary.

### Edge Cases

Complete source fingerprint/snapshot/phase/all blobs, exact review and source binding
are rechecked under lock before evidence creation, through staging/checkpoints,
immediately after the final stage read before rename, and before no-op/final success.
No-ops compile/recheck without journals/stages, though a lock file can be created.
Failure can leave a new pending transaction: fresh explicit existing recovery is
required, never source replay or automatic cleanup. Sibling bytes/inode/mtime/mode,
Stow links, and historical evidence remain protected; reads may affect atime.

No total filesystem deadline, pair-atomicity, runtime loading, or hostile-race
guarantee is established. No reload IPC is sent, but watchers may auto-reload.
At the b3 checkpoint, next was b4's distinct GUI historical restore action/lifetime
tests. Foreign preservation is now deferred and nonblocking for canonical-only migration.
M0/live UI, loader/watch acceptance, and rollout remain unverified.

### Example usage

Use the temporary-fixture preparation, review, explicit direct commit, and new-ID
recovery sequence in the [backend contract](architecture.md#m36b3-canonical-backend-restore-commit).
Do not invoke it against real state to satisfy automated validation.

### Related files

- `hyprmod/core/scoped_restore.py`, `hyprmod/core/transaction_publication.py`.
- `hyprmod/core/transaction_store.py`, `tests/test_scoped_restore_commit.py`.
- `hyprmod/pages/scope_recovery.py`: historical review was read-only at b3; existing
  transaction recovery action is not a historical restore action.
- [ROADMAP.md](../ROADMAP.md), [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility).

## M3.6b4: explicit GUI historical restore

### Overview and verification status

**Implemented and validated.** Final validation results:

- Required Ruff lint with fixes and formatting: passed; **193 files unchanged**.
- Full-tree Pyright with `--level error`: **zero errors**. Unfiltered dynamic GI
  source-resolution warnings still exist; this is not an all-warnings-clear claim.
- Full pytest suite: **3,137 passed, 207 skipped, 5 dependency deprecation warnings**,
  in **576.82 seconds**. For future full-suite runners use a **1,200,000 ms** timeout;
  the earlier 480-second budget is too short.
- Both isolated Broadway widget suites: **204 passed, 2 skipped**, with service
  writers mocked and compositor IPC disabled. The temporary daemon was stopped.
- Wheel build: passed, output under `/tmp/opencode/attune-m36b4-dist`. Installed
  launcher's `--help` and internal read-only worker `--help` for `list`/`prepare`:
  passed. Git diff whitespace check: passed.
- Independent review caught a **P2 setup-widget exception after ownership** that
  leaked writer authority. The fix defines completion before fallible setup,
  routes setup failure through pre-delegation cleanup, and keeps essential
  authority cleanup independent of individually guarded widget operations.
  **50 setup/cleanup regressions** and reentrant-owner checks passed. Recheck found
  no remaining blocking findings.

Earlier b1/b2/b3 counts and qualifications above remain historical checkpoint
evidence. No live GUI, user-state writes, compositor operations, loader edits, or
migration were performed. Nothing was installed, staged, or committed. B4's GUI
action is available in code, but live GUI behavior is not verified.

### API / Interfaces

`Commit Reviewed Historical Restore` consumes its own `ScopedRestoreDraft` after
complete both-scope CURRENT -> GOAL review. `Commit Reviewed Scope Recovery`
retains its separate `ScopedRecoveryDraft`/action. The shared direct non-daemon
writer validates exact `PublicationResult` types, IDs, outcomes and boolean flags;
read completions still validate exact DTO, roots and selection. Worker CLI modes
remain read-only `list`/`prepare` with 1 MiB/8 MiB transport, never mutation.

### Data Flow and validated coverage

Validated coverage includes:

- `tests/test_scope_recovery_gui.py`: separate historical/recovery draft routing,
  full both-scope review without implicit commit, dirty/preview/writer permission
  rechecks, consumed reviews/action rows, direct non-daemon lifetime and close veto.
- Exact result types/fields/IDs and outcome combinations; unknown/invalid results
  and post-delegation exceptions set both sticky flags. Constructor/start failure
  before delegation stays clean; failure after worker entry retains ownership until
  completion. Changed, no-op, journal-only, refused, pending and exception outcomes
  distinguish source from new restore IDs and never mark old baselines Saved.
- One-shot/reentrant completion, finish/feedback exceptions, independent sticky
  flags across later clean outcomes, and fresh refresh/review requirements.
- Setup-widget exceptions after ownership and cleanup-widget exceptions cannot
  retain authority or strand closure. Essential cleanup does not depend on any
  individual container/control update succeeding.
- `tests/test_startup_layout.py`, `tests/test_restore_window.py`: matching-owner
  release and sticky locking before fallible cache/widget notification, no stranded
  close veto, and no stale/mismatched finish releasing a new scope owner.
- The full suite also exercised temporary-only scoped restore/publication/store/
  recovery and legacy persistence/restoration/preservation regressions. Required
  checks and both opt-in isolated Broadway suites passed as recorded above.
  Writers were not invoked against real state.

### Edge Cases

Pending outcomes require fresh explicit transaction recovery for the **new restore
transaction**, never terminal-source replay or automatic recovery. Both current
scopes must be canonical. B5 subsequently added separate foreign-current diagnostics,
not preservation or writer authority. Automatic foreign preservation is deferred and
nonblocking for canonical-only M3.5 migration.
Unknown raw bytes must not become canonical priors. No reload IPC does not prevent
watcher auto-reload; separate renames are not pair-atomic. Lock/compiler limits are
not a hard total filesystem deadline. M0, live GUI and loader/watch rollout gates
remain pending.

### Example usage

The validated isolated widget sequence uses mocked mutators: browse and review a historical
scope/side, verify the recovery button stays disabled, then explicitly click the
historical commit. Inspect old/new IDs and pending/independent uncertainty flags.
Refresh assessment and prepare a fresh recovery review for a reported new pending
ID before explicitly committing recovery. Verify no automatic recovery occurs.

### Related files

- `hyprmod/pages/scope_recovery.py`, `hyprmod/main.py`, `hyprmod/window.py`.
- `hyprmod/core/scoped_restore.py`, `hyprmod/core/scoped_recovery.py`,
  `hyprmod/core/transaction_publication.py`.
- [architecture.md](architecture.md#m36b4-explicit-gui-historical-restore),
  [ROADMAP.md](../ROADMAP.md), [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility).

## M3.6b5: foreign-current diagnostic observer

### Overview and verification status

**Implemented and validated.** Final validation results:

- Ruff check with fixes and formatting: passed; **195 files unchanged**.
- Full-tree Pyright with `--level error`: **zero errors**. Unfiltered baseline GI
  source-resolution warnings remain; this is not an all-warnings-clear claim.
- Full pytest suite: **3,822 passed, 207 skipped, 5 dependency deprecation warnings**,
  in **580.72 seconds**. Default skips are mostly opt-in GTK cases.
- Both isolated Broadway suites: **204 passed, 2 skipped**, with writers mocked
  and compositor IPC disabled. The temporary daemon was stopped afterward.
- Focused foreign-current and route tests: **804 passed**, including **154 added
  public-observer cases** covering both scopes and leading-header variants.
- Wheel build: passed, output under `/tmp/opencode/attune-m36b5-dist`. Installed
  launcher's help and internal observer `--help` (observe-only): passed. Diff
  whitespace check: passed.
- Independent review's P2 hidden-unsupported-version finding was fixed. Final
  source-only review confirmed the finding resolved and found no blockers.

Previous checkpoint counts remain historical evidence, unchanged.
No live UI, user configuration/state writes, main Lua reads, compiler/IPC
operations, preservation/storage/provisioning or migration were performed for b5.
Test outputs/state were exclusively temporary; existing writer tests and mocked
widget compatibility checks do not imply a b5 writer or GUI. Nothing was installed,
staged or committed.
M3.6b remains incomplete; b4's canonical historical restore UI is still available.

### API / Interfaces

`scoped_foreign.observe_current`, `revalidate_current` and isolated `run_observe`
return distinct frozen `ScopedForeignObservation`, not foreign
`InstallationEvidence`. Selected raw text/hash/proof/status has no canonical
ID/counts; the opposite canonical sibling does. See the
[b5 contract](architecture.md#m36b5-foreign-current-diagnostic-observer) for bounds,
classification, exact-byte semantics and worker context checks.

### Data Flow and validated coverage

Validated `tests/test_scoped_foreign.py` coverage includes:

- Both selected scopes; foreign/damaged exact-marker text; exact CRLF, final-newline,
  BOM and Unicode retention; canonical same/wrong-scope v2 and v1 refusal; unknown
  prefix/embedded versions; strict UTF-8, controls and input/line boundaries.
- Shared filesystem policy, unsafe objects/modes/ownership, protected aliases,
  Git placement, Stow links, same-byte retargeting and dependency drift during
  collection/parsing/post-read/revalidation. Canonical inspection has an explicit
  after-parse dependency-change regression.
- Strict nested immutable DTOs before serialization, rehashed inconsistent semantics,
  UTC/context/hash checks, duplicate/unknown fields, depth/metadata and ASCII-escaped
  transport limits, pure decoding versus freshness, actual isolated worker transport,
  cancellation/deadlines/oversize responses and exact roots/selection echo.
- Forbidden-effect guards, no initialized-store requirement and no journal-content
  reads/scans even alongside pending/corrupt journal bytes.

Independent review found a P2: leading comments, blank lines or BOM could hide an
unsupported Attune record version behind whole-file prefix gating. After canonical
parse failure, detection now scans **all recognized record-header lines** regardless
of whole-file prefix. Leading BOM U+FEFF/ASCII space/tab is tolerated for detection
only. Explicit unsupported header versions and known headers containing decoded
JSON integer versions outside v1/v2 refuse. Exact raw text and exact-marker
`foreign`/`invalid-scoped` classification remain unchanged. The 154 added
public-observer cases exercise both scopes and leading-header variants; focused
foreign/route validation passed as recorded above. Final source-only review resolved
the P2 with no blockers.

Exercise alongside `tests/test_route_approval.py`, existing canonical restore,
transaction/recovery and legacy persistence/preservation regressions, then the
CONTRIBUTING gate and applicable isolated compatibility suites. Use exclusively
temporary HOME/XDG fixtures; never provision live state for validation.

### Edge Cases

Transaction contents are UNASSESSED. Diagnostic allowance alongside pending/corrupt
journals is neither writer authority nor conflict clearance/protection bypass.
No preservation storage, source/candidate/proposal/diff/commit, GUI activation,
provisioning, main Lua read, compiler or IPC is added. V1 fixtures and ordinary
ownership remain unchanged. Direct I/O is non-atomic and has no hard latency bound;
reads may affect atime. Hashes/decoding prove neither authentication nor runtime state.
Deferred work is separately designing raw-preservation evidence, journal/review contracts,
and writer authority under lock, including pending-conflict checks, before any
foreign mutator only, not canonical-only migration. Automatic foreign preservation
is deferred and nonblocking. M0 and live rollout gates remain pending.

### Example usage

Use the temporary-fixture observation/revalidation sequence in the b5 architecture
contract. Verify exact original bytes and absent newly created state. Do not treat
an observation as a restoration draft or initialize a store implicitly.

### Related files

- `hyprmod/core/scoped_foreign.py`, `hyprmod/core/route_approval.py`.
- `tests/test_scoped_foreign.py`, `tests/test_route_approval.py`.
- [ROADMAP.md](../ROADMAP.md),
  [ADR 0001](decisions/0001-shared-local-ownership.md#6-scope-aware-backup-and-preservation-compatibility).
