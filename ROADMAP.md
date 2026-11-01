# Attune roadmap

Updated: 2026-10-31

## Direction

Attune is a control surface for understanding, tuning, and recovering a Hyprland
workstation. Dotfiles remain authoritative. Attune integrates with the Arcana
ecosystem rather than replacing Wisp, wallpaper helpers, or authored workflows.

This file is the implementation backlog. [README.md](README.md) describes shipped
behavior; [docs/architecture.md](docs/architecture.md) describes its implementation.
Ideas here are not existing commands, compatibility guarantees, or release dates.

## Current baseline

**Current delivery:** existing registered canonical-pair normal editing, review,
Save, and continued editing are implemented and validated. Automated checks and
all three isolated Broadway suites passed; live acceptance remains pending. Next user value is
practical acceptance of this workflow and canonical-only opt-in migration, not
another recovery-foundation b6 slice. Automatic scoped foreign preservation is
parked, nonblocking work.

Implemented in the development checkout:

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

| Milestone | Status | Dependency | Outcome |
| --- | --- | --- | --- |
| M0: Validate the foundation | Pending manual acceptance | Existing baseline | Confidence in live previews and recovery |
| M1: Workstation diagnostics | Implemented: M1.1-M1.7 delivered | Existing baseline; may proceed alongside M0 | Read-only visibility into effective state and integration |
| M2: Recovery interface | Disk workflows delivered; M2.5 waits for M0 | M1 | Inspect and restore known Attune output through review |
| M3: Shared/local ownership split | Existing-pair editor implemented and validated; canonical-only migration next | Existing explicit registry/canonical pair/safe initialized store; live acceptance requires M0 permission | Edit, review, Save, and continue with portable appearance and local displays |
| M4: Constrained presets | Planned | M0 and M3 | Safe, deliberate visual and display modes |
| M5: Wisp integration | Planned | M1; preset entry points require M4 | Fast access without a second settings implementation |
| M6: CARAMEL appearance overview | Later | Existing helper contracts; M3 for saving appearance | Activity-aware presentation using existing tools |

Read-only diagnostics can ship before live acceptance is complete. New operations
that change compositor state must not bypass M0's acceptance gate. M5 can be split:
page navigation and status do not need to wait for presets.

## M0: Validate the foundation

Goal: prove the existing behavior on the actual workstation before broadening
the write surface. Run state-changing checks only with explicit permission.

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
- [ ] **Next implementation:** M3.5 reviewed canonical-only opt-in migration with rollback
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
- Wi-Fi, Bluetooth, printing, package management, general keybinding editing, and
  a replacement desktop shell remain outside this roadmap.
