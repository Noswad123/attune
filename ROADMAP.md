# Attune roadmap

Updated: 2026-11-05 UTC

## Direction

Attune is a control surface for understanding, tuning, and recovering a Hyprland
workstation. Dotfiles remain authoritative. Attune integrates with the Arcana
ecosystem rather than replacing Wisp, wallpaper helpers, or authored workflows.

This file is the implementation backlog. [README.md](README.md) describes shipped
behavior; [docs/architecture.md](docs/architecture.md) describes its implementation.
Ideas here are not existing commands, compatibility guarantees, or release dates.

## Current baseline

**UI correction:** implemented and validated. One stable
Keybindings list retains all 80 rows; every pencil opens Edit Source Shortcut.
There is no Delete button, Assign New or Unassigned expander. On the installed
default TSV (not Prepared): pencil -> clear Shortcut -> Update Pending -> Review
Source -> Save Source. The row remains blank in place after Save/restart and its
dialog opens empty. Pending says Clear shortcut; Disable retains the assigned key
off. Backend/state/schema and installed bridge capabilities are unchanged; no
deployment is needed. Counts and former UI descriptions below are historical,
not final validation of this correction. Its final full pytest **4,361 passed, 383
skipped** and six Broadway suites **380 passed, 2 skipped** are recorded in
[current validation](docs/validation.md#ui-only-correction-final-validation).
No new milestone or scope change is added; live behavior remains unverified.

**Current delivery:** additional managed bindings have an automated/isolated GTK
validated checkpoint, not live keyboard/loading acceptance. Source-aware existing
shortcuts have an earlier automated/isolated GTK checkpoint. The approved 80-row
integration was deployed on 2026-11-02 with all runtime descriptions observed.
The reversible disable fix is implemented and validated in code through automated
and isolated GTK checks. The user-approved compatible companion-bridge-only update
is installed, preserving user TSV and main Lua. The on-disk capability guard passes;
live TSV remains all 80 enabled, with no Super+T
disable performed. Live shortcut behavior acceptance remains pending.
True Delete/unassignment is implemented and validated in code and isolated tests.
The approved Delete-capable bridge-only deployment completed on 2026-11-03 UTC:
installed `1d1023aa...` supports both capabilities, with main Lua and mappings unchanged.
Installed-default pencil/clear/Update Pending/Review Source/Save Source needs no
deployment. No user data was deleted or disabled by this documentation pass.
**Current Cursor delivery: implemented, final validation pending.** The user accepted
the Input checkpoint ("so far so good") and approved Cursor work with "continue"
after Cursor was proposed next. This is not live Input loading/device proof.
Historical Devices-only full pytest: **4,632 passed, 483 skipped**; eight isolated Broadway suites:
**480 passed, 2 skipped**. Required checks/build/help and parent diff check passed;
independent backend/UI review found no remaining material findings. Existing-shortcut
live acceptance remains pending independently. Earlier counts below are historical.
Those counts do not validate Cursor. See [pending final checks](docs/validation.md#cursor-implemented-final-validation-pending).
Rules, startup and environment remain separately scoped later work, not automatic
expansion. Profiles and layout pages remain off scope. Canonical-pair editing has an
earlier validated checkpoint; its results do not validate the new bindings feature.
Live acceptance remains pending. Migration and automatic scoped foreign preservation
are parked, nonblocking work, not prerequisites for feature breadth.

Implemented in the development checkout:

- Devices with draft-only Keyboard/Mouse/Touchpad controls: 15 keys in 14 rows,
  paired layouts/variants, raw XKB options and conservative 0.1–2.0 scroll factors.
  Independent reviewed Save to `attune-input.lua`, dedicated lock/private backups,
  existing-parent/Stow safety and unit-local uncertainty. No input preview, mutation
  IPC, automatic loader/include/reload, or visual v1/v2/registry/journal expansion.
  Historical offline validation passed; the user accepted the checkpoint, not live loading/device proof.
- Cursor: eight native keys/eight widgets, draft-only, sharing Input's single owner,
  combined review/Save/Discard/baseline/undo, output, lock and backups. The closed
  Input allowlist is 23 keys; no fifth save unit, visual scope, registry or journal.
  Zoom/timeout use precise locale-aware entries with explicit Apply and decimal 0.1
  +/− steps that apply, without a one-decimal grid. Unapplied numeric text survives
  unrelated edits/Undo/Redo outside review; Discard/saved adoption are authoritative.
  Backend finite/bounded floats retain public library emission-proof refusal for
  unrepresentable precision. Other float spin rows remain unchanged.
  Theme/size/environment, `set_cursor`, GSettings and hardware/render controls are
  excluded. Final validation remains pending; no live behavior is claimed.
- Existing shortcuts tab with Open Prepared Source Mappings, key/description/enabled
  TSV edits, complete source review and independent Save. IDs/context/submap/base flags/
  order and authored actions remain unchanged. Candidate main/bridge/80 stable IDs
  are in `integrations/hyprland/jdawson`, outside watched dotfiles. No app main-Lua
  evaluation, installer or runtime unbinding is added. Disable code validation passed;
   compatible bridge is installed; runtime disable behavior and live acceptance remain pending. The original
  three-file installation is complete, not to be repeated for this fix.
- Dedicated Attune-owned global keyboard bindings, implemented and validated:
  searchable local drafts and read-only runtime/opaque inventory, separate reviewed
  Save to `attune-bindings.lua`, independent of visual v1/v2 and migration. No live
  apply/unbind/override, main-Lua read, auto-import, include insertion or reload.
- Attune identity, editable development environment, and Makefile installation.
- Focused appearance, display, animation, and Bezier controls.
- Pending Changes review with a separate explicit save action.
- One canonical `attune.lua`, read without executing Lua.
- Symlink-preserving saves, previous-output backups, and stale-review checks.
- Preservation of unchanged saved values and disconnected display directives.
- Isolated persistence, section, state, packaging, and GTK smoke tests.
- Read-only Health observations, asynchronous refresh, and recovery-screen access.
- Redacted diagnostics preview/copy, bounded scalar drift comparison, and explicit
  plain-text editor/file-manager actions.
- Read-only backup listing, canonical/hash checks, and backup-to-current diffs in
  both normal navigation and startup recovery.
- Separate validated restoration drafts and reviewed disk-only replacement of
  existing owned output, with rollback backups and cached-editor invalidation.
- Explicit preservation-first recovery of bounded foreign/invalid text, isolated
  from ordinary saves and restoration, with private exact-byte evidence.
- Scoped models/codec, explicit route inspection, complete group reviews, and
  journaled publication now support existing-pair GUI Save. Frozen v1 compatibility
  remains unchanged. Registry creation, store initialization, missing/empty target
  provisioning, migration, and runtime loader handoff remain separate work.
- M3.6a transaction recovery frontend and legacy exclusion, completed in code:
  bounded asynchronous startup assessment, explicit both-scope recovery reviews,
  protected direct commits, and cache/editor invalidation on uncertainty.
- M3.6b2 explicit historical source browsing and complete read-only both-scope
  review, implemented and validated at the b2 checkpoint.
- M3.6b3 canonical backend restore commit, implemented and validated:
  explicit direct mutator with under-lock source checks and a new ordinary transaction.
- M3.6b4 separate GUI historical restore and shared protected writer lifetime,
  implemented and validated. Live GUI behavior is not verified.
- M3.6b5 backend-only foreign-current diagnostic observer, implemented and validated.
  No preservation or foreign writer is implemented.

Live display/HDR and animation behavior still requires manual acceptance. Automated
and isolated GTK checks are not evidence that the workstation integration is done.
Persistent loading, Stow provisioning, and desktop registration remain opt-in.

## Milestones and order

Product order now takes precedence over the historical M-number sequence:

1. Useful existing bindings: the compatible bridge-only deployment is complete.
   The UI correction is implemented and validated. Next: user pencil/clear/
   Update Pending/Review Source/Save Source against installed defaults and live acceptance.
   Earlier additional-binding checks do not establish this acceptance.
2. Device/Input: historical offline checkpoint accepted by the user. Keep its
   [evidence and limits](docs/validation.md#deviceinput-validated-offline-user-acceptance-pending),
   without inferring live loading/device verification.
3. Cursor: approved and implemented, pending final checks and the
   [limited checklist](docs/validation.md#cursor-implemented-final-validation-pending).
   Rules, startup and environment remain separately scoped later slices.

Do not add profiles/layout pages or require more migration/foreign-repair machinery
before these features. Existing mutating live checks still require explicit permission.

### Additional bindings: earlier validated checkpoint

- [x] Record actual lint/type/full-suite and focused/isolated GTK results in
  `docs/validation.md`: full suite 4,026 passed, 299 skipped; five Broadway suites
  296 passed, 2 skipped; backend focus 88 passed. Ruff/format, error-level Pyright,
  wheel/help and diff checks passed. Warning and isolation qualifications are recorded.
- [x] Verify in automated/isolated checks search/add/edit/delete for owned global `bind`/`binde`/`bindl`/`bindr`/`bindn`,
  GTK-only recording/manual fallback, runtime/opaque read-only rows with unknown
  origins, conservative new/moved conflicts, same-combo local edits and unknown offline
  inventory. Claim only flags supplied by the installed client, not complete Lua flags.
- [x] Verify in temporary fixtures fixed-path protected/Stow publication, existing-parent requirement,
  foreign/unknown manual remediation, dedicated lock/private backups, non-daemon close
  veto, uncertainty locking only bindings, and independent visual/bindings dirty/undo.
- [x] Verify first-save guidance: manual `dofile` with actual absolute path only after
  output exists; no loader insertion/reload and no persisted-equals-loaded claim.
- [x] Resolve review findings: exact literal command emission, backup-root Git guards,
  exact dialog argument fallback and owned-baseline Revert with uniqueness checks.
  Source-only independent rechecks confirmed all four original findings resolved.
- [ ] Live keyboard/capture semantics, manual loading and watcher behavior remain
  unverified and require separate explicit permission.

### Existing shortcuts: Delete code validated, compatible bridge deployed

The completed validation items below retain the historical pre-correction UI;
they do not validate the current unified list. Current instructions are at the top.

- [x] Prepare the user-approved offline declarations/labels refactor, separate from
  unchanged Lua callbacks. Reported runtime inventory was 80 `__lua` rows with zero
  descriptions; numeric registry references cannot supply an action editor.
- [x] Implement source metadata selection/edit/review/Save, independently of additional
  managed bindings and visuals. Opening prepared data needs no live installation.
- [x] Record original key/description-only results: full-tree Ruff check/fix and format passed (210
  files unchanged), error-level Pyright zero errors with baseline GI warnings;
  full pytest 4,291 passed, 343 skipped; all six Broadway suites 340 passed, 2 skipped.
  IPC disabled; writers mocked by default, explicit real publishers temporary only.
  Wheel/help/diff checks passed. Timings/warnings/isolation: `docs/validation.md`.
- [x] Validate focused equivalence (114 passed), including permanent custom key/
  description cases for all 80 IDs, read-error/helper-syntax fallbacks, default
  symbolic trace and byte-for-byte reverse restoration; source backend 149 passed.
- [x] Resolve actual-config-root alias protection, immediate watched-TSV reload
  warning and explicit Additional bindings pending-row navigation. Independent
  rechecks found no blockers. These checks are not live behavior proof.
- [x] Complete the separately approved three-file deployment and observe all 80
  descriptions, unchanged keys/flags/native contexts and zero config errors.
- [x] Validate reversible Disable/Enable, dialog Enabled switch,
  state-aware Pending/Undo/Redo/Discard/Revert, active-only combo conflicts and atomic
  re-enable refusal. Retain all 80 records, restoration keys/descriptions and callbacks;
  derive state from metadata-only `disabled`, preserving v1/all-enabled bytes and
  catalog/IDs/context/submap/base flags/order. Earlier counts do not validate this fix.
- [x] Record disable validation: full pytest 4,332 passed, 367 skipped; six Broadway
  suites 364 passed, 2 skipped; backend/equivalence 304 passed; source GUI 68 passed.
  Full-tree Ruff/format, error-level Pyright, wheel/candidate syntax/launcher help/diff
  checks passed. Warning, timing and isolation details are in `docs/validation.md`.
- [x] Resolve the P1 direct-Stow bypass: capture/transport/recheck the actual installed
  TSV route; a shared target or device/inode requires both selected and installed
  companions' capability headers and protected proofs. Old/missing actual helpers
  refuse direct writer calls before state/data writes. Both-new success, unrelated
  offline editing, stale retarget/helper refusal and own-leaf post-write verification
  are covered. Independent source-only review found P1 resolved and no blockers.
- [x] Complete the explicitly user-approved compatible **bridge-only update**, preserving
  main Lua and TSV, with private backups and exact readback. Installed observation and
  in-memory-only disable review pass; no persistence or Super+T disable occurred.
  Runtime metadata remains unchanged; this does not prove new-helper loading or
  disabled-key behavior. Historical tests were not rerun for this code-unchanged deployment.
- [x] Complete final validation of true Delete versus Disable, implemented in
  the checkout. Delete/blank-field clearing stores exactly empty key without `disabled`,
  removing the old combo, not an off tombstone. Disable retains the assigned key;
  enabled means assigned and not disabled; empty+disabled is invalid. Keep all 80
  declarations, immutable ID/context/submap/base flags/order and authored callbacks.
   The former Assigned shortcuts (N) excluded unassigned actions; collapsed Unassigned
   actions offered Assign New starting empty. Pending Delete was Removed, Disable Modified;
  Undo/Redo/Discard/Revert preserve enabled/disabled/unassigned states.
- [x] Validate Save/reopen and repeated compatible-bridge loads of valid saved data
  without default resurrection. Missing/broken helper or invalid catalog still uses
  whole defaults. Existing valid assigned data, disabled format and v1 schema stay
  unchanged. Candidate helper retains first-line `disabled-v1`, adds second-line
  `unassigned-v1`; any unassigned proposal requires both markers on selected and
  relevant installed companions under the existing alias guard, at review and commit.
- [x] Record final validation: full pytest **4,361 passed, 383 skipped, 12 dependency
  warnings, 783.67 seconds**; six Broadway suites **380 passed, 2 skipped, 6,332
  dependency warnings, 138.21 seconds**. Required Ruff/format passed (210 files
  unchanged); full-tree error-level Pyright zero errors, not GI-warning clearance.
  Independent review found no material findings. Review-run backend/equivalence
  332 passed and source GUI 82 passed; post-review mixed-state disk roundtrip (1 pass)
  and actual Pending Delete/key reuse/Revert (2 cases, both modes) are included in
  final suites. Wheel/syntax/help/diff passed. Final suites used process HOME/XDG set
  before Python; the earlier non-prefixed 767.71-second run was rerun properly.
  See `docs/validation.md` for qualifications and unchanged live hashes. No live update.
- [x] Complete explicitly approved Delete-capable **bridge-only** deployment, preserving
  main Lua and mappings. Both capability headers and separate in-memory Delete/Disable
  reviews pass without persistence. All 80 remain assigned/enabled. App code is unchanged;
  no full-suite rerun is claimed. See the deployment record for hashes and private evidence.
- [ ] Ready now, without another deployment approval gate: the user closes/reopens Attune
  for the new UI and fresh bridge proof, confirms installed default TSV (not Prepared),
   finds Open terminal (T) / `terminal.t`, clicks its pencil, clears Shortcut, chooses
   Update Pending, Reviews Source and Saves Source. Expect all 80 rows in the same
   order, that shortcut blank after Save/restart and its dialog empty. Do not perform these actions
  for the user. Both disabled and unassigned rows are consumed but not passed to
  `hl.bind`; never forward `disabled` as an option. Effects occur on configuration
  load, not automatic IPC. Watcher reload is unproven and may occur immediately;
  Ctrl+S/visual Save is not source Save. Reload configuration if needed; the user chooses
  any manual command, which can reset unsaved live previews. No reload IPC was sent.
- [ ] Validate actual shortcut behavior,
  including manager Lua-state gating, Wisp native submap and hardware/pointer flags.
  Isolated 80-registration equivalence is not live callback behavior proof.

The compatible bridge-only update is complete; next is the user's installed-default
pencil/clear/Update Pending/Review/Save and live acceptance, not another deployment request.
Do not repeat the original three-file installation, replace main/data, migrate TSV
or expand Device/Input breadth now. Earlier counts above remain historical; only
the earlier Delete checkpoint validates its former code/widgets, not this UI correction or live behavior.
See the [deployment record](docs/validation.md#approved-delete-capable-bridge-only-deployment).
No rollback is recorded. The prior disable-only helper cannot accept empty keys: do
not blindly downgrade after Delete and resurrect defaults. Require fresh compatibility
review and user reassignment or a safe updated-helper plan; never
restore snapshot TSV over later edits.

### Device/Input: validated offline, user acceptance pending

Historical Devices-only checkpoint. The user subsequently accepted this checkpoint
and approved Cursor work; these counts are not current Cursor validation or live proof.

Devices exposes Keyboard, Mouse and Touchpad in both admitted legacy and pair editors.
Local edit/review/**Save Reviewed Input**/reopen/repeat uses a typed closed dedicated
`attune-input.lua`, not shared appearance v2 or a third registry scope. Bindings and
Input immediately share only narrow fixed-output safety/review/writer mechanics;
source retains its independent TSV workflow with safety-helper imports, protected
name updates and narrow `same_source` review matching. All four save units retain
the others' drafts/baselines/undo.

- Implemented at this checkpoint: 15 Devices keys in 14 rows, paired layout/variant operations and
  one Undo, raw unknown XKB option preservation, labeled read-only runtime/default
  fallbacks with owned data preferred, no overrides merely from opening the page.
- Implemented: complete bounded worker review, direct non-daemon writer, global
  owner exclusion/close veto, dedicated `input.lock`/private `input-backups`, fresh
  checks and Input-only locking on uncertainty. Safe existing parent required;
  Stow/Git output is allowed without automatic staging. State stays outside Git.
- [x] Complete final parent validation: full pytest **4,632 passed, 483 skipped**;
  eight isolated Broadway suites **480 passed, 2 skipped**. Ruff/format, error-level
  Pyright, wheel/help and parent diff checks passed. Independent backend/UI review:
  no remaining material findings, P2s resolved. Timings, warnings and isolation are in
  [validation](docs/validation.md#deviceinput-validated-offline-user-acceptance-pending).
- [x] Resolve sequential four-unit saves without weakening reviewed publication:
  new reviews may refresh only safe known sibling regular/absent leaf proofs; own
  source/Git, paths/symlinks/ancestors, main/bridge/registry and Source installed route
  stay strict. Writers bind full exact reviewed evidence under lock/final checks.
  GUI retains original baseline identity, proposal/revision/draft/undo until adopting
  only its own verified result. All 12 ordered unit pairs in both modes passed 24
  real-publisher GUI cases, each saving all four units; focused backend 684 passed.
- [x] Preserve unapplied keyboard-options text across unrelated edits, without
  bypassing Apply. Visible row origins distinguish Saved/Draft/Runtime/Default and
  explicitly label unapplied text as not in the draft.
- [x] User checkpoint acceptance ("so far so good"), followed by approval to proceed
  with Cursor ("continue"). This is scope approval, not live loading/device proof.
- [ ] Complete final Cursor validation and record actual results. Devices and Cursor
  must share one complete review/Save with edit invalidation from either view, one
  dirty/undo unit and shared locking on uncertainty, retaining all other units.
  Manual `dofile` uses the actual absolute path only after output exists. Future live
  loading/checks require explicit permission; persistence is not loading.

No live input preview/mutations, automatic include/reload, profiles, window layouts,
per-device hardware matching, global device disable or keymap-file editing. Touchpad
disable-while-typing is not device disable. Scroll factors stay at 0.1–2.0 in 0.1
steps, not an unverified 10. Migration and foreign recovery remain deferred/nonblocking.

### Historical milestone inventory

| Milestone | Status | Dependency | Outcome |
| --- | --- | --- | --- |
| M0: Validate the foundation | Pending manual acceptance | Existing baseline | Confidence in live previews and recovery |
| M1: Workstation diagnostics | Implemented: M1.1-M1.7 delivered | Existing baseline; may proceed alongside M0 | Read-only visibility into effective state and integration |
| M2: Recovery interface | Disk workflows delivered; M2.5 waits for M0 | M1 | Inspect and restore known Attune output through review |
| M3: Shared/local ownership split | Existing-pair editor validated at earlier checkpoint; migration deferred | Existing explicit registry/canonical pair/safe initialized store; live acceptance requires M0 permission | Edit, review, Save, and continue with portable appearance and local displays |
| M4: Constrained presets | Planned | M0 and M3 | Safe, deliberate visual and display modes |
| M5: Wisp integration | Planned | M1; preset entry points require M4 | Fast access without a second settings implementation |
| M6: CARAMEL appearance overview | Later | Existing helper contracts; M3 for saving appearance | Activity-aware presentation using existing tools |

Read-only diagnostics can ship before live acceptance is complete. New operations
that change compositor state must not bypass M0's acceptance gate. M5 can be split:
page navigation and status do not need to wait for presets.

## M0: Validate the foundation

Goal: prove applicable behavior on the actual workstation before claiming live
acceptance. Offline feature development may proceed. Run state-changing checks only
with explicit permission.

- [ ] M0.1 Record the running Hyprland version and the tested hardware/topology.
- [ ] M0.2 Exercise scalar preview, undo, discard, reviewed save, and reopening.
- [ ] M0.3 Exercise animation enable/disable and same-name Bezier point changes.
- [ ] M0.4 Test monitor Keep/Revert, timeout, and closure/SIGINT/SIGTERM while a
  preview is pending. Confirm a rejected preview cannot silently persist.
- [ ] M0.5 Test disconnect/reconnect, scaling, refresh rate, and rotation. Test HDR
  only where supported; record unsupported or untested cases rather than passing them.
- [ ] M0.6 Verify deliberate Lua loading and removal of overrides against authored
  defaults. Record how saves become effective; do not assume automatic reload.
- [ ] M0.7 Repeat a reviewed save through an explicitly provisioned Stow link and
  inspect the resolved repository change and backup.

Acceptance: record dated results in `docs/validation.md`, including failures,
untested cases, and recovery steps. Fix critical persistence or rollback failures
before introducing additional mutating workflows.

## M1: Workstation diagnostics

Goal: make Attune useful even when nothing is being changed.

- [x] M1.1 Add a GTK-independent, read-only health snapshot service with structured
  results for available, unavailable, unknown, and failed observations.
- [x] M1.2 Report compositor version/reachability, configuration errors, and
  connected displays with their effective mode, scale, position, and refresh rate.
- [x] M1.3 Show Attune's lexical output path, resolved Stow destination, ownership
  validity, Lua-validator availability, and backup availability.
- [x] M1.4 Add a Health page with explicit refresh, observation time, and per-check
  errors. Perform potentially slow IPC/filesystem work off the GTK main thread
  with bounded waits and no overlapping refreshes.
- [x] M1.5 Add copyable diagnostics with a preview and sensible path redaction.
  Do not collect environment dumps, unrelated files, or credentials.
- [x] M1.6 Compare supported saved values with runtime values, labeling differences
  as drift, not proof of a broken configuration or ownership of the live value.
  Show last-save information only when supported by recorded evidence.
- [x] M1.7 Offer explicit actions to open the managed file or its containing
  directory. Opening must not execute the configuration or change settings.

Acceptance: offline startup, unavailable IPC, invalid/foreign output, missing Lua,
and missing backups produce useful partial results without freezing the UI or
writing files. Repeated refreshes perform no reloads or repair actions. Do not
claim the output is loaded merely because the file exists.

M1.1 through M1.7 are implemented. Service tests, isolated GTK coverage, and
read-only live collector/drift checks are recorded in
[docs/validation.md](docs/validation.md). No M0 mutating acceptance is implied.
Reports deliberately export only allowlisted summaries; raw paths, errors, display
identities, and drift values are omitted. Drift covers supported saved scalar
options, not monitor/animation definitions or Beziers. No last-save timestamp is
claimed because none is recorded. External editor/file-manager integration remains
subject to the local default associations and manual desktop acceptance.
M2.1-M2.4 inspection and reviewed disk-only restoration are now available.

## M2: Recovery interface

Goal: turn existing backup files into a usable, reviewable recovery workflow.

- [x] M2.1 List backups with content identity, readable summary, and available
  filesystem metadata. Hash-addressed backups are not a chronological save journal.
- [x] M2.2 Compare a selected backup with current output without executing Lua.
- [x] M2.3 Stage a restoration as a draft using existing scope/ownership validation.
  Never copy a backup directly over an authored file.
- [x] M2.4 Require an exact diff review and fresh destination/content checks before
  saving. Back up current valid output before replacement.
- [ ] M2.5 Separate restoring disk content from live application. Any live monitor
  application must use the confirmation/rollback workflow.
- [x] M2.6 Provide a recovery path when current managed output is invalid or
  externally edited. Preserve those bytes separately; recovery must be explicit
  and must not weaken the ordinary foreign-file overwrite guard.

Acceptance: corrupt backups, incompatible data, stale reviews, and backup/write
failures leave the destination intact. A successful restoration can itself be
reversed. Cover symlink targets and foreign-output recovery in regression tests.

Delivered inspection remains read-only and uses backup -> current diffs. Separate
restoration uses a complete current -> backup review and compile-only validation.
Ordinary restoration requires existing nonempty canonical owned output;
foreign/missing/invalid targets remain refused by that path. Pending edits or
monitor confirmation block restoration and recovery.
After replacement or an uncertain outcome, the cached editor stays disabled until
restart. The prior output receives a hash-addressed rollback backup.

Attune sends no live-apply or reload commands during restoration, but Hyprland may
auto-reload watched files. This distinction is explicit in the review. No M0 live
acceptance or M2.5 implementation is implied by the disk-only workflow.

M2.6 adds a distinct acknowledged recovery review for foreign/invalid UTF-8 text.
It verifies private exact-byte preservation before replacement and leaves normal
save/restoration guards intact. Binary, missing, empty, unsafe, and oversized input
remain unsupported; preserved raw bytes are manual evidence, not canonical backups.

Existing canonical-pair routing is implemented and validated; migration
and initial provisioning are not implemented.
M2.5 live application and routing rollout remain gated by M0 manual acceptance and
explicit permission for state-changing checks.

## M3: Shared appearance and machine-local displays

Goal: keep appearance portable without exporting a machine's display topology.

### Product priorities

- [x] **Existing-pair normal editor, implemented and validated:** admit an existing explicitly
  registered canonical pair with safe initialized storage and a full terminal-only
  journal scan; normal pages use local pair models, dirty-only proposals, complete
  asynchronous both-scope review, direct journaled Save, and fresh exact post-save
  baselines for repeated Saves. Keep `legacy-clear` v1 behavior unchanged.
- [x] **Reviewed Save and continue:** exact both-scope review, direct mature writer,
  fresh verified baselines, repeated Saves/reopen, and real temporary monitor-model
  Save/reopen coverage preserving disconnected records and appearance identity.
- [x] **Automated validation:** required checks, full suite, all three isolated
  Broadway suites, build/help and diff checks passed. Results: `docs/validation.md`.
- [ ] **Next manual acceptance:** only after separate user confirmation, exercise
  the short [manual acceptance checklist](docs/validation.md#manual-acceptance-checklist).
  M0 remains explicitly pending, especially monitor/HDR and loader/watch behavior.
- [ ] **Deferred implementation:** M3.5 reviewed canonical-only opt-in migration with rollback
  material and manual loader handoff. Define absent/empty provisioning states
  separately; the ordinary present-owned writer does not support them today.
- **Deferred, nonblocking:** automatic scoped foreign preservation/replacement.
  Foreign/invalid targets require manual remediation, never overwrite or fallback.
  This is not a prerequisite for existing-pair editing or canonical-only migration.

### Historical implementation checkpoints

The b1-b5 details below record delivered supporting work, not the current shipping
critical path. Current editor validation is recorded separately from those results.

- [x] M3.1 Record a design decision for owned filenames, scope routing, explicit
  destination configuration, and load order before changing the format.
- [x] M3.2 Model and explicitly partition general visual settings, decoration,
  animations/Beziers, and monitor directives into pure appearance/display scopes,
  with strict registry declarations and canonical v2 codecs. V1 fixtures stay frozen.
- [x] M3.3 Extend canonical ownership, reviewed destination binding, backups, and
  diagnostics to each designated file. Do not replace path guards with unrestricted
  output selection or infer destinations from a hardcoded username/repository path.
  - [x] M3.3a Inspect explicit filesystem routes and capture immutable, revalidatable
    evidence for both correctly scoped outputs, registry, and protected paths.
  - [x] M3.3b Build scope-aware review/backup/diagnostic adapters around that evidence,
    retaining inactive split writes until the journaled transaction layer exists.
- [x] M3.4 Implement and validate the journaled multi-file failure/recovery protocol
  selected in the design decision. Separate atomic replacements do not make a
  multi-file transaction atomic.
  - [x] M3.4a Define private evidence/journal records and interrupted-state
    classification before introducing any output publication.
  - [x] M3.4b Implement guarded publication and explicitly reviewed resume/rollback,
    with failure/crash injection and unchanged-scope isolation.
- [ ] M3.5 Provide a reviewed, opt-in migration from the single file, with rollback
  material and manual loader instructions. Avoid double-loading old/new overrides;
  do not edit the authored entrypoint or silently delete the old file.
- [x] M3.6 Canonical recovery understands legacy output and registered v2 groups.
  Migration and its tests remain separate before recommending a new default.
  - [x] M3.6a Transaction recovery frontend and legacy exclusion, completed in code.
    Assess startup off GTK; construct the v1 editor only for `legacy-clear`.
    Expose explicit resume/rollback/finalize/abandon with complete CURRENT -> GOAL
    reviews of both scopes, direct non-daemon commits, close veto, owner-aware
    exclusion, and independent scope/journal uncertainty invalidation. Any registry
    or transaction evidence, including terminal history, blocks v1 writes;
    uninspectable metadata fails closed. Full and isolated GTK validation is
    recorded in `docs/validation.md`; live rollout remains gated.
  - [x] M3.6b Canonical scope-local v2 recovery: restore b1-b4 and diagnostics b5
    are delivered. Automatic foreign preservation is deferred and nonblocking;
    legacy bundles still require explicit conversion.
    - [x] M3.6b1-b2 Canonical historical preparation, explicit browsing, and complete
      both-scope review, with a full journal safety scan independent of display caps.
    - [x] M3.6b3-b4 New-transaction canonical restore backend and distinct reviewed
      GUI commit, preserving current siblings, Stow links and historical evidence.
    - [x] M3.6b5 Backend-only bounded foreign-current diagnostics, not a foreign writer
      or conflict-clearance check. Existing ownership guards remain unchanged.
    - Parked: automatic foreign preservation/replacement requires its own protocol,
      never raw originals in canonical rollback blobs. Not a canonical M3.5 blocker.

Service contracts are in [architecture.md](docs/architecture.md); historical counts
and qualifications remain in [validation.md](docs/validation.md).

Acceptance: changing only appearance leaves display output unchanged and vice
versa. Both files work through Stow links. Simulated second-write failures and
interrupted migrations are recoverable without losing the previous working setup.

Design: [ADR 0001](docs/decisions/0001-shared-local-ownership.md) selects explicitly
registered `attune-appearance.lua` and `attune-displays.lua`, strict scope-tagged
v2 data, and journaled disk recovery rather than claiming pair-atomic replacement.
The first split policy keeps registry/display storage outside Git, supports local
Stow sources, and leaves appearance eligible for tracked dotfiles. Existing v1
files/backups remain legacy full bundles until an explicit reviewed migration.

The mature writer supports present-owned canonical priors only. Absent/empty target
states remain separate migration/provisioning work; preparation is not publication
approval, and journal progress is not runtime-loading proof.
The implemented and validated existing-pair editor consumes the mature writer for
ordinary reviewed Save. V1 remains available only for `legacy-clear` and is
excluded whenever scoped evidence is present. No registry or store is created by
startup/Save. Foreign/missing/invalid scopes, unsafe/missing stores, and pending or
corrupt history fail closed with explicit recovery or manual-remediation guidance.
Old terminal recovery actual-conflicts do not invalidate a healthy current pair.
Runtime rollout still requires M0 acceptance; never run automatic loader edits,
activation, recovery, or live reloads to satisfy a checkbox.

## M4: Constrained visual and display presets

Goal: provide named modes without restoring upstream's unrestricted profiles.

- [ ] M4.1 Define a versioned preset format restricted to Attune-owned settings,
  with clear appearance/display scope and no shell commands or startup behavior.
- [ ] M4.2 Implement save/name/list and preview, starting with user-defined presets.
  Candidate examples are Focus, Presentation, Gaming, Docked, and Undocked; their
  actual values must be chosen and tested rather than assumed universally safe.
- [ ] M4.3 Capture the pre-preview runtime baseline and support Keep/Revert.
  Validate all targets before applying; define partial-IPC failure rollback.
- [ ] M4.4 Match displays using deliberate identifiers. Missing or ambiguous
  hardware must produce a clear choice, not an arbitrary fallback arrangement.
- [ ] M4.5 Make preview acceptance and persistence separate. Permanent output still
  requires the exact reviewed-save workflow.

Acceptance: cancel/timeout restores the captured baseline where IPC permits, with
visible failures if it cannot. Invalid/unsupported presets do not partially apply
silently. Docking events and startup do not automatically activate presets.

## M5: Wisp integration

Goal: give existing actions a stable Attune entry point, not duplicate the editor.

- [ ] M5.1 Define a small command contract for page navigation and read-only status,
  including stable exit codes and a machine-readable status representation.
- [ ] M5.2 Route navigation to the existing application instance and report unknown
  pages/arguments without activating dormant upstream profile commands.
- [ ] M5.3 Add preset-preview navigation after M4, retaining the same Keep/Revert
  lifecycle and separate persistence review. Do not introduce a silent save CLI.
- [ ] M5.4 Document optional Wisp actions. Changes to Wisp catalogs or dotfiles are
  separate, explicit integration work, not side effects of installing Attune.

Proposed interfaces, not implemented commands:

```text
attune open health
attune open displays
attune status --json
attune preset preview focus
```

Acceptance: commands work from outside the checkout, offline status remains useful,
and IPC errors produce actionable exit codes. Navigation/status do not change
configuration, reload Hyprland, or register desktop files.

## M6: CARAMEL appearance overview

Goal: present activities, wallpapers, and visual identity without taking ownership
of activity bindings or inventing another wallpaper manager.

- [ ] M6.1 Identify an explicit read-only source for activity metadata and wallpaper
  associations. Do not execute or scrape arbitrary main Lua to discover them.
- [ ] M6.2 Show an activity overview with names, existing wallpaper associations,
  and previews. Handle missing images/helpers gracefully.
- [ ] M6.3 Define a narrow interface to the existing wallpaper helper for requested
  changes; keep its implementation and ownership in that tool.
- [ ] M6.4 Optionally suggest accent/border palettes from a selected wallpaper.
  Suggestions are previews and require deliberate application and persistence.

Acceptance: no duplicated wallpaper daemon, hidden activity switching, or global
keybinding rewrites. Missing helpers leave the rest of Attune usable.

## Delivery rules

- Prioritize user-facing delivery over expanding recovery minutiae. Distinguish
  implemented-pending-validation work from validated checkpoints; check off items
  only after their validation is complete.
- Ship small slices with pure-logic tests, isolated GTK checks, and applicable
  live acceptance. Follow [CONTRIBUTING.md](CONTRIBUTING.md) for required checks.
- Add discovered work under its milestone rather than silently expanding scope.
- Update README/architecture/changelog when behavior ships. Keep pending designs
  here rather than documenting them as available features.
- No automatic commits, pushes, loader edits, service installation, startup
  repair, or privileged operations. Preserve upstream attribution and licensing.
- Wi-Fi, Bluetooth, printing, package management, arbitrary authored-keybinding editing,
  profiles/layout pages, and
  a replacement desktop shell remain outside this roadmap.
