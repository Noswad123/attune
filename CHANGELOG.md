# Changelog

Notable changes to Attune are documented here. Releases through 0.5.0 below
are retained upstream HyprMod history, not a list of this fork's supported features.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Source shortcut disable fix: implemented and validated in code

- Address the key/description-only editor's inability to remove Super+T with
  reversible Disable/Enable and an Enabled switch. Enabled state uses a metadata-only
  `disabled` token in the existing v1 flags column; all-enabled bytes stay unchanged.
  Preserve all 80 records, keys/descriptions for restoration, authored callbacks,
  catalog/IDs/context/submap/base flags/order. Pending removal/addition entries,
  Undo/Redo/Discard/Revert include state. Disabled combos are reusable by enabled
  source rows; conflicting re-enable refuses atomically. The project bridge consumes
  all 80 IDs but skips `hl.bind` for disabled rows and never forwards that token.
- Review/commit require the companion's `disabled-v1` capability header and captured
  bridge proof for disabled proposals. Old/missing helpers explicitly block Save:
  the old bridge would reject the token and restore all 80 defaults. Old all-enabled
  data stays readable by both bridges. Only the project candidate helper is updated;
  installed live bridge/TSV remain untouched and all 80 rows enabled. No Super+T
  disable was performed. Next activation requires explicit approval for a compatible
  bridge-only update preserving user TSV, not main replacement or auto-migration.
  The saved removal takes effect on the next configuration load, with watcher reload
  unproven and no IPC sent. No commands/tests/live changes/staging/commits
  were performed by this documentation pass. Foreign/profiles/layout scope is unchanged.
- Fix the P1 direct-Stow compatibility bypass: `SourceBaseline.installed_route`
  captures the actual config-root TSV's metadata proof with strict JSON validation.
  A shared resolved target or device/inode requires both selected and installed
  companions' capability headers/protected proofs. Installed route and helpers are
  rechecked before state creation, under lock and before replacement. Post-save
  verification allows only the selected regular leaf's own identity change, including
  its aliased installed route; unrelated offline TSVs stay independent. No main Lua
  read/evaluation. Regressions cover old/missing actual helper refusing direct writer
  calls before state/data writes, both-new success, offline independence and stale
  symlink/helper changes. Independent source-only review confirmed P1 resolved,
  with no blockers.
- Validation passed: full-tree Ruff `--fix`/format (210 files unchanged); full-tree
  Pyright `--level error` zero errors, with unfiltered GI warnings remaining. Full
  pytest **4,332 passed, 367 skipped, 13 dependency warnings**, **753.75 seconds**;
  all six Broadway suites **364 passed, 2 skipped, 5,939 dependency warnings**,
  **111.22 seconds**. Focused backend/equivalence **304 passed**; source GUI **68 passed**,
  including disable Super+T, source view/flags/review, temporary Save/reopen, re-enable,
  combo reuse and atomic conflict refusal. IPC disabled, writers mocked by default;
  explicit real source/managed/pair publishers temporary only; daemon stopped.
  Wheel `/tmp/opencode/attune-source-disable-dist`, updated candidate bridge `luac -p`,
  installed launcher `--help` and diff check passed. Process HOME/XDG isolated;
  sentinel and final read-only live hashes unchanged. No live writes, user-key
  changes, Super+T disable, bridge installation, reload, staging or commits occurred.
  See `docs/validation.md` for hashes and the separate helper-only approval gate.

### Added

The source-editor entry below retains the original key/description-only checkpoint
and its then-offline effects report. The later approved deployment is recorded in
`docs/validation.md`; the disable fix above is not covered by these historical counts.

- Source-aware **Existing shortcuts** tab, **implemented and validated** through
  automated and isolated GTK checks. Open Prepared Source Mappings opens the offline 80-row TSV now;
  explicit file selection also supports existing `keybindings.tsv`. Only keys and
  descriptions are editable; IDs/context/native submap/flags/order and authored Lua
  actions stay fixed. Complete source review and **Save Reviewed Source Shortcuts**
  form a third independent save unit beside additional bindings and visuals, with
  dedicated lock/private TSV backups, route/byte rechecks and source-local uncertainty.
  Existing generated managed formats are unchanged. The user-approved offline
  main/bridge/data candidate in `integrations/hyprland/jdawson` separates declarations
  and labels from unchanged callback definition sites. Whole-catalog bridge validation
  falls back to all defaults; a missing/unloadable bridge retains source defaults.
  Data is TSV, never Lua evaluation, with no bridge JSON dependency. Reported runtime
  inventory was all 80 `__lua`, zero descriptions; numeric arguments are registry
  references, not source lines/code. Runtime descriptions are preferred when present.
  No app authored-main execution, live keymap change, watched-dotfiles write,
  installation or reload occurred. Isolated registration-equivalence evidence is
  not live behavior proof. Activation needs separate manual approval due to watcher
  auto-reload risk. Useful existing bindings remain the priority before Device/Input.
  Historical validation: full-tree Ruff check/fix and format passed (210 files
  unchanged); Pyright `--level error` zero errors, with baseline unfiltered GI
  warnings remaining. Full pytest: **4,291 passed, 343 skipped, 12 dependency
  warnings**, **744.17 seconds**. All six Broadway suites: **340 passed, 2 skipped,
  5,498 dependency warnings**, **91.35 seconds**, IPC disabled; writers mocked by
  default, explicit real source/managed/pair publishers temporary only; daemon stopped.
  Focused equivalence **114 passed**, with permanent custom key/description coverage
  for all 80 IDs, virtual mapping read-error/helper-syntax fallback and original
  callback byte-for-byte reverse restoration/default symbolic trace. Source backend
  focus **149 passed**. Wheel `/tmp/opencode/attune-source-bindings-dist`, installed
  launcher help, read-only source worker observe/review help and diff check passed.
  Resolved P2 actual-config-root alias protection with baseline config context and
  protected proofs, honest immediate watched-TSV reload warning, and explicit
  Additional bindings pending-row routing. Independent rechecks found no blockers.
  Process HOME/XDG isolation preceded Python; sentinel and dotfiles stayed unchanged
  except the preexisting untracked empty `attune.lua`, left untouched with no
  attributed origin. See `docs/validation.md` for evidence and safety qualifications.

- Dedicated managed Keybindings workflow, **implemented and validated**:
  searchable owned saved/draft rows, draft-only add/edit/delete for global keyboard
  `bind`/`binde`/`bindl`/`bindr`/`bindn`, GTK-only recording with manual fallback,
  and read-only runtime/opaque inventory with unproven origins. New/moved shortcuts
  refuse observed overlaps; same-combo owned edits remain local with warnings.
  Offline inventory is unknown, not conflict-free. Distinct bindings-format v1 at
  `$XDG_CONFIG_HOME/hypr/attune-bindings.lua` works with admitted legacy/pair editors
  without migration or a new visual scope. Separate **Save Reviewed Keybindings**
  and **Save Reviewed Appearance / Displays** preserve the other unit's dirty/undo
  state; there is no atomic Save Everything. Dedicated lock/private hash backups,
  protected fixed-path/Stow checks, compile-only validation, direct non-daemon commit,
  close veto and fresh verified baseline protect publication; uncertain results lock
  only bindings. Foreign/unknown output requires manual remediation, never import.
  First save requires manual `dofile` integration using the actual absolute path
  only after output exists. No main-Lua read, include insertion, override, unbind,
  live application or reload IPC; watchers may auto-reload, and saved is not loaded.
  Validation: full-tree Ruff `--fix` and format passed (205 files unchanged);
  full-tree Pyright `--level error` found zero errors, with baseline unfiltered GI
  warnings remaining. Full pytest: **4,026 passed, 299 skipped, 13 dependency warnings**
  in **737.65 seconds**. All five isolated Broadway suites: **296 passed, 2 skipped,
  4,707 dependency warnings** in **64.37 seconds**, IPC disabled, mutators mocked by
  default except explicitly real temporary publishers; daemon stopped. Backend focus:
  **88 passed**. Wheel build (`/tmp/opencode/attune-keybindings-dist`), installed
  launcher `--help`, internal read-only bindings worker help and diff check passed.
  Review fixes cover literal command emission, backup-root Git checks, exact dialog
  argument preservation and owned-baseline Revert. Source-only independent rechecks
  confirmed all four findings resolved. See `docs/validation.md` for the corrected
  initial navigation-test failure and unexplained empty live-file observation;
  its origin is not established and the file was left untouched. No live keyboard
  semantics, manual loading or watcher behavior is verified; no new mutator CLI.
  These are the earlier additional-bindings checkpoint, not source-editor results.
  Useful existing shortcuts now precede Device/Input; migration/foreign repair remain
  deferred and nonblocking.

- Existing explicitly registered canonical-pair normal edit/review/Save/continue,
  **implemented and validated**. Startup requires both canonical
  v2 scopes, safe initialized storage, and a full terminal-only journal scan, not
  old recovery actual-conflict classification. Local pair models avoid v1 cache
  reads; dirty-only proposals preserve untouched data. Bounded asynchronous both-scope
  precomputed review is invalidated by edits. Explicit Save uses the mature direct
  non-daemon journaled writer with a new transaction, close veto and owner exclusion.
  Fresh post-save verification of exact reviewed goals/routes precedes baseline
  adoption and marking saved, enabling repeated Saves. Failures retain dirty edits;
  pending/uncertain outcomes or failed post-read verification lock editing. Settings
  reports paired routes and labels Health/Backups as legacy-v1-only. Blocked entry
  gives explicit recovery/manual-remediation guidance without overwrite or repair.
  Legacy-clear v1 remains unchanged. No registry/store creation, absent/empty target
  provisioning, loader edits, reload IPC, migration or new mutating CLI is added.
  Validation: required Ruff checks/format passed (199 files unchanged); full-tree
  Pyright error-level check found zero errors (baseline unfiltered GI warnings
  remain); full pytest **3,907 passed, 231 skipped**, with 5 dependency warnings.
  All three isolated Broadway suites: **228 passed, 2 skipped**. IPC is disabled and
  mutators are mocked by default; explicit pair-Save end-to-end tests use the real
  publisher with temporary outputs/store only. Build/help/diff checks passed.
  No live UI, user-state mutation, loader change, migration or provisioning occurred.
  See `docs/validation.md` for timings, review results and remaining manual acceptance.

The following implementation entries retain historical checkpoint results and scope
limitations. Earlier references to inactive split Save or preservation preceding
migration are superseded by the current delivery and priority decisions above/below.

- M3.6b5 backend-only foreign-current diagnostic observer, implemented and validated.
  `observe_current`, `revalidate_current`, and supervised
  `run_observe` return distinct frozen raw-selected/canonical-sibling observations,
  never foreign `InstallationEvidence` or canonical IDs/counts for raw originals.
  Exact UTF-8 bytes, CRLF and final-newline presence are retained within 1 MiB per
  scope/10,000 selected lines, 1 MiB metadata, and 8 MiB ASCII transport/depth-24 bounds.
  Private collection shares existing filesystem policy without a public
  `allow_foreign` flag; canonical inspection still requires both canonical scopes
  and rechecks dependencies after parsing. Transaction contents remain UNASSESSED:
  no initialized store or journal scan is required for diagnostics, not authority.
  No preservation storage, source/candidate/proposal/diff/commit, GUI activation,
  provisioning, main Lua read, compiler invocation or IPC is added. B4 remains
  available; v1 fixtures and ordinary ownership are unchanged. M3.6b is incomplete:
  raw-preservation evidence, journal/review contracts and writer authority under lock,
  including pending-conflict checks, need separate design before a foreign mutator
  only, not canonical-only migration. Independent review's P2 leading-comment/blank/BOM version-detection
  gap is fixed: after canonical parse failure, scan all recognized record-header
  lines regardless of whole-file prefix. Leading BOM/ASCII space/tab tolerance is
  detection-only; unsupported header or embedded JSON integer versions refuse
  without changing raw bytes or exact-marker status. Added 154 public-observer
  regressions cover both scopes; focused foreign/route tests: 804 passed. Final
  source review found no blockers. Full suite: 3,822 passed, 207 skipped; both
  isolated Broadway suites: 204 passed, 2 skipped. Required checks/build/help passed;
  full results and warning qualifications are in `docs/validation.md`. No b5 GUI,
  live operations, installation, staging or commits were added/performed.
- M3.6b4 explicit **Commit Reviewed Historical Restore**, implemented and validated.
  Complete both-scope review populates its own
  `ScopedRestoreDraft`, never the transaction recovery draft; neither browsing nor
  preparation implicitly commits. Both actions share a direct non-daemon writer,
  permission/exclusion gates, close veto, and exact typed result/ID/flag validation.
  Invalid post-delegation outcomes set independent sticky scope/journal uncertainty;
  pre-delegation worker-start failure adds none. Reviews/action rows are consumed;
  fresh refresh/review is required. Outcomes distinguish old source from new restore
  transaction and direct pending cases to fresh explicit recovery of the new ID,
  never automatic recovery. Matching-owner release and sticky editor locking precede
  fallible cache/widget notifications; old baselines are never marked Saved.
  Independent review's setup-widget writer leak is fixed: completion is defined
  before setup, setup failures use pre-delegation cleanup, and essential authority
  cleanup is independent of individually guarded widget operations. Recheck found
  no remaining blocking findings; validation results are in `docs/validation.md`.
  Live GUI behavior is not verified. At the b4 checkpoint, separate foreign-current
  diagnostics followed; automatic foreign preservation is now deferred and nonblocking
  for canonical-only migration, never unknown raw bytes as canonical priors. No mutator CLI or
  reload IPC is added; watchers may auto-reload changed files.
- M3.6b3 canonical backend restore commit, implemented and validated.
  Explicit `scoped_restore.commit_restore` writes only the selected canonical scope
  via a new ordinary transaction, preserving the current sibling, Stow links, and
  historical source evidence. Original immutable draft validation precedes JSON
  copying; complete source fingerprints/snapshots/phases/blobs and exact review/
  source binding are rechecked under lock through staging/checkpoints, after the
  final stage read before rename, and before no-op/final success. Generated ID
  collisions refuse rather than reuse PREPARED history. Direct non-daemon calls
  preserve backend result flags; b3 adds no killable commit child, CLI, or GUI
  historical commit. No-ops compile/recheck without journals/stages, though a lock
  file is possible. Failures can require explicit existing recovery of the new
  transaction, never terminal-source replay. Temporary-only fault and real
  `os._exit` tests are present; no passing b3 results are claimed here. M3.6b remains
  incomplete at that checkpoint: b4's distinct GUI action/lifetime tests followed.
  Foreign preservation is now deferred, not a migration prerequisite. No total filesystem deadline or
  reload IPC is promised; watchers may auto-reload replacements.
- M3.6b2 historical source browsing/review in Scope Recovery. Explicit browsing
  displays at most 32 transactions with
  four canonical scope/side sources each after full bounded journal safety scans.
  Display truncation is separate from scan completeness; pending/corrupt evidence
  globally blocks, while incompatible historical routes block only their rows when
  global inspection is safe. Complete read-only CURRENT -> GOAL reviews include the
  unchanged current sibling and cannot enable transaction recovery commit. Isolated
  `list`/`prepare` workers share one asynchronous page read slot, with 1 MiB/8 MiB
  transport limits. B2 adds no startup listing, provisioning, or historical restore commit.
  Phase/hashes are not installed-byte proof, runtime/compiler validation, or
  authentication. At the b2 checkpoint, under-lock source freshness and a new
  restore transaction were next; M3.6b remains incomplete.
- Strict page read-result mode/context/selection checks prevent historical reads
  from entering recovery commit paths. Positive scoped history discovery locks
  running legacy editors while retaining pending changes.
- M3.6b1 inactive read-only scoped restore preparation. Strict frozen drafts bind a
  verified terminal source's selected canonical prior/proposed scope to a complete
  CURRENT -> GOAL review with the
  current sibling unchanged. Safe initialized storage, canonical current outputs,
  matching installation identity, and before/after pending-evidence checks are
  required even for no-ops. Isolated `-I -B` preparation has bounded strict transport;
  fingerprints are observations, not authentication or write permits. No source
  browser, frontend, commit, compiler, provisioning, foreign preservation, or
  migration is added. M3.6b remains In progress; ordinary ownership is unchanged.
- M3.6a transaction recovery frontend, completed in code: bounded asynchronous
  read-only startup assessment opens the v1 editor only for `legacy-clear` and
  otherwise exposes a recovery shell, including on assessment errors. Scope
  Recovery requires separate complete CURRENT -> GOAL review of both scopes and
  explicit commit for resume, rollback, finalize, or abandon. Read-only workers
  are isolated and bounded; commits are direct non-daemon workers with close veto,
  owner-aware exclusion, and independent scope/journal uncertainty invalidation.
  Split editing, split publication through Save, activation, and migration remain
  unavailable. M3.6b scope-local v2 backup restore/preservation is still pending.
- Inactive M3.4b guarded split publication and explicit complete CURRENT -> GOAL
  recovery reviews for resume, rollback, finalize, and abandon. Compile-only
  preflight, synchronized staging, private atomic checkpoints, and crash-resumable
  rollback preserve unchanged scopes without claiming pair-atomic publication.
  These core APIs write when explicitly called; M3.6a later integrates recovery
  only. Split Save/CLI publication, activation, migration, and v2 editor routing
  remain unavailable.
- Failure-boundary and real process-death recovery coverage using exclusively
  temporary outputs/state, including checkpoint scratch collision refusal even
  for identical bytes. Existing scratch is never promoted, reused, or deleted.
- Inactive private transaction records and explicitly initialized evidence storage,
  with verified content-addressed blobs, group snapshots, and prepared intents.
- Read-only interrupted-state classification from actual scoped bytes and fresh
  bindings, without trusting journal progress; publication/recovery is a separate API.
- Inactive scoped group-review plans bound to fresh filesystem evidence, with
  complete per-scope diffs and exact unchanged-sibling preservation.
- Pure v1/v2 backup descriptors and fresh scoped diagnostics with an allowlisted
  report projection omitting paths, hashes, raw values, and private metadata.
  Existing GUI, backup routing, and v1 persistence remain unchanged.
- Inactive read-only split-route inspection with stable file/symlink evidence,
  ownership and permission checks, protected-path/alias guards, Git-placement
  policy, and stale-evidence revalidation. No registry creation or split writes.
- Inactive M3.2 appearance/display scope models, explicit legacy-bundle partition,
  canonical v2 codec with scope-local content identities, and pure strict registry
  declarations. Existing GUI/configuration/persistence remains v1-only.
- Literal historical v1 fixtures and hashes to verify byte-for-byte renderer and
  backup compatibility without regenerating expected data during tests.
- M3.1 architecture decision for future shared appearance/local display ownership,
  scoped v2 data, journaled transactions, and explicit migration handoff. This is
  a design record only; current output, loaders, and routing are unchanged.
- Distinct acknowledged preservation-first recovery of foreign/invalid text from a
  validated backup. Exact original bytes are privately preserved and synchronized
  before replacement; ordinary save/restoration guards remain unchanged.
- Separate complete restoration review for existing owned output, with immutable
  source/destination-bound drafts, compile-only validation, rollback backups,
  protected disk writes, and editor locking after restored or uncertain outcomes.
- Read-only Backups browser in normal and recovery navigation, with bounded
  hash/canonical inspection, descriptive filesystem metadata, and precomputed
  backup-to-current diffs. Invalid, missing, foreign, oversized, and truncated
  results remain explicit; no restore or live-apply controls are provided.
- Health diagnostics preview/copy with an allowlisted redacted summary and frozen
  copy contents, plus explicit asynchronous plain-text editor and folder actions.
- Bounded saved/runtime scalar drift observations with type-aware normalization,
  partial/unknown results, and no automatic correction or inference of file loading.
- Read-only Health page with bounded asynchronous observations for compositor
  version, configuration errors, effective displays, output ownership, validator
  discovery, and backup candidates. Invalid output retains recovery-screen Health
  access. Refreshes support cancellation and preserve stale results on failure.
- Project roadmap with phased diagnostics, recovery, configuration ownership,
  presets, Wisp, and CARAMEL milestones and explicit acceptance criteria.
- Makefile development build and install targets. `make install` copies the
  editable environment's launcher into `~/.local/bin` without desktop registration.
- Attune personal fork of BlueManCZ/hyprmod at `b475087`, retaining upstream
  attribution and GPL-3.0-or-later licensing. The public command is `attune`;
  the internal `hyprmod` namespace is intentionally retained.
- Focused appearance/general visual, decoration, animation/bezier, and monitor
  editing, with Pending Changes review and read-only integration settings.
- Restricted persistence in `hyprmod/core/persistence.py`: one dedicated
  `attune.lua` for monitors and appearance, canonical ownership/data records read
  without Lua execution, compile-only syntax checks, resolved-destination-bound
  review, symlink-preserving writes, and hash-named backups outside Git.
- Local-source setup, explicit manual Lua integration instructions, development
  guidance, and an architecture reference. Shared/machine output splitting is
  not active application behavior; the inactive backend is documented separately.

### Changed

- Corrected stale-disk guidance: pair sessions cannot adopt external file/route
  edits. Manually correct or restore registered canonical files/routes, then
  restart/reopen; retained edits are session-local, and review retry is for temporary
  failures only. Scope Recovery copy now consistently states that reviewed canonical
  historical restore is available while foreign preservation/migration are not.
- Prioritize main user-facing features: practical acceptance of the current app and
  existing canonical-pair editing, followed by canonical-only opt-in migration.
  Automatic scoped foreign preservation is deferred, nonblocking work, not a
  prerequisite for canonical editing or migration. Foreign/invalid targets still
  fail closed and require manual remediation. M0 remains pending explicit manual
  acceptance; the short checklist in `docs/validation.md` authorizes no live effects.
- Any registry or transaction evidence, including terminal history, now excludes
  v1 save, restoration, and preservation-first replacement. Unsafe or uninspectable
  metadata fails closed. Discovery of scoped evidence locks the legacy editor
  while retaining pending changes; old baselines are never marked saved by recovery.
- Ordinary saves now also invalidate cached editor state on possibly-written
  persistence failures rather than leaving an already-written draft editable.
- Moved the development checkout to `~/Projects/attune`, rebuilt its environment,
  and refreshed the installed development launcher for the new path.
- Editor saves and restoration now share the protected persistence transaction,
  including finite/cancellable lock waits and exclusive rollback-file creation.
- Restoration invalidates managed-data caches so recovery retries cannot reuse
  pre-restoration disk values. Live apply/reload and foreign-output replacement
  remain excluded; watched files may still be auto-reloaded by Hyprland.
- Deeply nested malformed owned-record JSON now becomes a validation error so
  recovery remains available rather than leaking a decoder recursion failure.
- The focused application leaves hand-authored behavior outside the GUI, with no
  profiles CLI, auto-save, main Lua parsing, automatic include insertion,
  migrations, startup reload, or silent desktop registration.
- Ctrl+S opens review; only Save Reviewed Changes persists output. Removing an
  override previews a schema default; reloading the authored config after saving
  is needed to restore its baseline.
- Disabled the inherited network `install.sh`. It now exits nonzero with local
  uv setup guidance instead of installing upstream HyprMod.

## [0.5.0] - 2026-10-07

### Added

- Plugins page for configuring Hyprland plugins: a schema-driven UI for natively supported plugins (starting with Hypr Dynamic Cursors) plus a list editor for arbitrary `plugin { … }` settings, with live-apply, detection of plugin settings from your existing config, and a prompt to add `hyprpm reload` to autostart when a supported plugin is not loaded (#60)
- The window rule dialog supports multiple actions per rule: actions are a dynamic list of blocks that can be added and removed individually, instead of a single action per rule; anonymous rules with multiple effects now also load as one rule instead of splitting into separate entries (#57, #58)
- The keybind dialog's "Run command" action can pick from installed apps: a search button next to the Command field opens the same app picker used by autostart entries, filling the field with the selected app's command

### Changed

- The window rule dialog autofills new condition rows from the last picked window: after picking a window, "+ Condition" pre-fills the matching value, and changing a condition's type from the dropdown updates the value to match the picked window (#56)

### Fixed

- A Norwegian keyboard layout is saved and applied correctly in Lua mode. Its xkb code is `no`, which is also one of Hyprland's boolean words, so HyprMod wrote `kb_layout = false` and the compositor rejected it with "string type requires a string". Every string-typed setting whose value starts with `no`, `on` or `off` was affected, and an already-correct layout was rewritten on the next save of any unrelated setting. Requires hyprland-config 0.9.19 (#96)
- Opaque Lua callbacks, custom dispatchers, and parsed bind variants the editor cannot safely represent are now read-only. Editing one previously selected the first available action and could save an empty `exec` command, silently breaking the shortcut (#88)
- A described keybind from a Lua config shows its real action again. Omarchy's `SUPER + B` read as `Browser`, the description Hyprland reports ahead of the dispatcher, so HyprMod had no command to show or edit. Requires hyprland-config 0.9.18 (#88)
- A Lua config that prints something no longer stops HyprMod from starting. The reader took the config's stdout output as part of its own data and failed to parse it, so the first launch showed nothing and every launch after that showed an empty window. A config HyprMod genuinely cannot read now gets a window saying what the parser rejected, with a retry, instead of a traceback in the terminal. Requires hyprland-config 0.9.17 (#87)
- The Mode picked for a "Toggle fullscreen" keybind is saved again in Lua mode. Every mode emitted `hl.dsp.window.fullscreen()`, so a bind set to Maximize toggled full screen instead. The "No gaps" mode is gone from the picker: Hyprland has read every mode but Maximize as full screen since 0.43, so it never did anything. Requires hyprland-config 0.9.16 (#86)
- Editing a window rule to drop an action, or narrowing its conditions so a window no longer matches, now releases the windows it was applied to. HyprMod also set each effect as a per-window property in Lua mode, and those outrank the rule and survive a config reload. Requires hyprland-state 0.4.7 (#79)
- A window rule with more than one action now applies all of them when pushed to the running compositor, instead of only the first. Requires hyprland-config 0.9.15 (#79)
- Saving now reloads the compositor when window or layer rules changed, so deleting, reordering, or discarding a rule takes effect instead of waiting for the next HyprMod launch. Hyprland's autoreload never saw the write: it watches the config file's inode, and an atomic save replaces it (#79)
- Re-running `install.sh` updates HyprMod itself again, not just its dependencies. It ran `uv tool upgrade`, which re-resolves dependencies but can keep the git commit already installed; it now reinstalls from the source URL (#79)
- Setting a rotated monitor back to Normal now works in Lua mode; the display stayed rotated and the Transform dropdown snapped back to the old angle. Hyprland's Lua config keeps the previous value for any key left out of an applied monitor line, and the line omitted `transform` when it was 0. Clearing a Bit Depth or Color Management override was broken the same way. Requires hyprland-monitors 0.9.0 and hyprland-state 0.4.6 (#82)
- pycairo is declared as a direct dependency, so packagers no longer end up with an install where the monitor layout preview, the bezier curve editor, and the animation preview are blank. PyGObject needs pycairo to hand a drawing context to Python, and distro packages of PyGObject list pycairo as optional, so drawing failed with nothing shown to the user. An install that is still missing the bindings now says so in a dialog at startup instead of just drawing empty boxes (#78)
- Recording a media, brightness, or other `XF86` key in the keybind dialog no longer produces a bind Hyprland rejects with "Unknown keysym"; GDK reports these keysyms without their `XF86` prefix (`AudioRaiseVolume`), which is not a name xkb resolves, so the prefix is now restored before the key reaches the config (#69)
- Recording a shortcut whose key sits on a shifted or AltGr level no longer produces a bind that never fires; Hyprland matches binds against the base-level keysym, so the captured key is now resolved with every modifier cleared instead of only `SHIFT`, fixing AltGr+Q on a Czech layout being recorded as `MOD5, backslash` where Hyprland only ever looks for `q` (#69)
- Recording a shortcut while a secondary keyboard layout is active no longer produces a bind that never fires; unless `resolve_binds_by_sym` is set, Hyprland resolves binds through the first layout in `input:kb_layout` regardless of which one is active, so on `cz,us` the number row key recorded as `2` from the us layout is now recorded as `ecaron` (#73)
- The "Resize window" keybind action now takes a width and a height with a relative/exact mode picker, instead of a free-text argument field. It sits among direction-picker actions, so the old field invited a direction letter that Hyprland cannot resize by and the bind failed to apply. Percentage values keep the text field, since they have no spin-button form (#70)
- Ten keybind actions that had no Lua translation, among them "Move window or group", "Pass key to window" and "Lock all groups", no longer fail with "No Lua mapping" in Lua mode; requires hyprland-config 0.9.13 (#74)
- The installed desktop entry launches from app menus and docks again: `Exec` now points at the absolute path of the hyprmod binary, since GUI launchers often start without `~/.local/bin` on `$PATH` (#67)
- Window rules with multiple effects no longer lose every effect after the first when saved in Lua mode; rule lines are now normalized so the Lua serializer emits all effects (#60)
- Changing a condition from a boolean type (like `xwayland`) to a text type (like `initial_class`) no longer leaves the literal string `"false"` in the value field (#56)

## [0.4.0] - 2026-07-01

### Added

- Command-line profile switching (#50): `hyprmod profile apply <name>` switches profiles without opening the window (bindable to a keybind or scriptable), `hyprmod profile next` / `previous` cycle through them alphabetically (wrapping around, great for a single keybind), and `hyprmod profile list` shows the saved profiles with the active one marked. The profile list, in the app and on the command line, is now ordered alphabetically
- Multiple keyboard layouts (#44): the Keyboard layouts row opens a dialog to add, reorder, edit, and remove input sources (a layout plus its variant), written to `kb_layout` and `kb_variant`

### Changed

- The Gestures page is hidden when there's no touchpad or touchscreen, since its workspace-swipe options need one to do anything. With only one device present, the page stays and the unusable subsection greys out

### Fixed

- Changing the active or inactive window border color in Lua mode no longer fails with an `invalid color` error; a single-color border was sent to Hyprland with a redundant `0deg` angle that its Lua config manager rejected (#43)
- Migrating a `hyprland.conf` to Lua no longer drops or breaks keybinds: concatenated and mixed-case modifiers (`SUPERSHIFT`, `Alt`) now decompose into canonical tokens, and nested `match { … }` blocks in block-form `windowrule`/`layerrule` nest correctly instead of being rejected (#45)
- Disabling a monitor no longer makes it vanish from the Monitors page; hyprmod now reads disabled outputs too, so a turned-off monitor stays listed and can be switched back on (https://github.com/BlueManCZ/hyprland-socket/pull/2)
- Re-enabling a disabled monitor no longer overlaps or snaps onto another monitor, comes back at its preferred mode when Hyprland reports `0x0` after a reboot, and no longer crashes the Monitors page with `scales must not be empty` (#46)
- Workspace rules in generated Lua configs now write the workspace selector as a string (`workspace = "1"` instead of `workspace = 1`); `hl.workspace_rule` declares the field as a string, and the integer form relied on Lua's implicit coercion and was flagged by lua-language-server (#48)
- "Refresh monitors" no longer discards unsaved monitor changes and clears the pending-changes indicator
- The workspace rule dialog's appearance overrides are now single "Use global / On / Off" dropdowns; the previous override-switch-plus-value-switch pair could keep showing "On" after the value was switched off
- Binds using the `global` dispatcher (app-registered global shortcuts, e.g. `bind = SUPER, period, global, caelestia:emoji`) no longer fail to apply in Lua mode; the dispatcher had no Lua mapping (#49)
- The first-run setup dialog no longer reappears when HyprMod's include line lives in a sourced sub-file rather than directly in `hyprland.lua` / `hyprland.conf`; detection now follows the whole `source` / `require` / `dofile` chain instead of inspecting only the top-level entrypoint (#51)
- Migrating to Lua no longer breaks keybinds that use a modifier variable (`$shiftMod = $mainMod SHIFT`); the variable now joins its modifiers with `+` instead of leaking a space-separated `SUPER SHIFT` blob that Hyprland reads as a single unknown keysym (#52)
- Migrating to Lua no longer breaks workspace `layoutopt` rules; `layoutopt:direction:right` now becomes a nested `layout_opts` table instead of a flat string that `hl.workspace_rule` rejects (#53)

## [0.3.0] - 2026-05-25

### Added

- Lua config support — read and edit `hyprland.lua` directly, with live preview against Hyprland 0.55+'s Lua runtime
- "Migrate to Lua…" wizard and main-window banner (Hyprland 0.55+) — converts your active `hyprland.conf` to `hyprland.lua`, rewrites the entrypoint include, and is dismissible
- Per-monitor "Identify by description" toggle — emits `monitor=desc:…` instead of `monitor=DP-1, …` so the saved configuration follows the physical monitor across port changes (#26)
- Per-monitor HDR controls — expanded Color Management presets (Auto/sRGB/Adobe/Wide/EDID/HDR/HDR EDID), SDR Brightness/Saturation sliders, advanced SDR/HDR luminance sliders, lock-step luminance controls, and safe defaults for first-time HDR setup (#29)
- Workspaces page — manage `workspace` rules with live preview and live IPC apply (#31)
- Deprecation assistant — detect and migrate deprecated Hyprland syntax with explicit user confirmation and timestamped backups
- Convenience installer (`install.sh`) and `hyprmod --install` / `--uninstall` flags — `pipx`/`uv tool` installs now register a desktop launcher entry and icon under `$XDG_DATA_HOME`, with first-launch self-registration as a fallback
- Optional Name and Enabled fields in the window and layer rule dialogs for Hyprland's block-form / Lua named rules
- "Report a bug" link in Help menu and error toasts — opens prefilled GitHub issues with HyprMod version, Hyprland version, config language, and install method

### Changed

- Bind dialog's Manual Edit modifier picker is a compact two-row chip strip instead of stacked switch rows
- Options unavailable on the running Hyprland version are hidden instead of greyed-out; group headers collapse when every row in the group is unavailable
- Profiles transcode on activation — saving in Hyprlang then activating in Lua (or vice-versa) just works
- HyprMod no longer auto-migrates deprecated syntax silently on save; migrations are surfaced via the new deprecation assistant and require explicit user confirmation

### Fixed

- Keybinds using the Hyper modifier (and `CAPS`/`MOD2`/`MOD3`/`MOD5`) are now displayed and recorded correctly — previously `Caps Lock + G` under `caps:hyper` rendered as `+ G` and Record captured only `G` (#27)
- Toggling "Numlock by default" wrote an invalid `input:kb_numlock` option that Hyprland rejected on reload; the option is now written as `input:numlock_by_default` per the schema (#34)
- Rules from your managed config no longer leak into the read-only "external rules" list when `hyprland-gui.conf` is reached through a symlinked path (typical dotfiles setup)
- Named window and layer rules (block-form `windowrule { name = … }` or Lua `name = "…"`) are now recognized and editable instead of being silently dropped (#37)
- Autostart page surfaces `exec` / `exec-once` entries defined in your `hyprland.conf` (or any file it sources) as read-only rows alongside the managed ones, matching the existing behavior of the Env Variables, Window Rules, and Layer Rules pages (#37)
- Lua migration preserves Hyprlang `$var` references as named Lua locals instead of inlining their values or emitting literal `"$var"` strings that Hyprland rejected on reload (#38)
- Deleting or disabling a window rule with `float`, `tile`, `pin`, `fullscreen`, or `maximize` now reverts the effect on matching open windows instead of waiting for the next Hyprland reload
- Per-monitor VRR `Off` now writes `vrr, 0` and actually disables VRR; a new `Use global` option preserves the previous omit-the-clause behavior (#39)
- Window and layer rules now apply correctly on Hyprland < 0.53 and < 0.54, which expect the pre-v3 `windowrulev2` / `layerrule = effect, namespace` grammar; the v3 `match:` form hyprmod previously always emitted was rejected with `Invalid rulev2 found` (#41)

## [0.2.0] - 2026-05-07

### Added

- Window Rules page — manage `windowrule` entries with a window picker, curated action dropdown, and live preview
- Layer Rules page — manage `layerrule` entries with curated presets and live preview
- Autostart page — manage `exec` and `exec-once` entries with an app picker
- Env Variables page — manage `env` entries with POSIX name validation
- Pending Changes page — review every unsaved edit across the app in one place
- Mouse-drag (`bindm`) keybinds with dispatcher, category, and preset support (#20)
- Profile cards show the last-modified date alongside the option count

### Changed

- Sidebar reorganized by task
- Dwindle, Master, and Scrolling merged into a single Layouts page
- Profiles page redesigned — active profile promoted to a hero card with the saved-profiles list below
- Saving keeps the active profile in sync automatically; use the save split button's "without updating profile" option to intentionally diverge

### Fixed

- Gradient border colors written without `0x` prefix on save, causing Hyprland to reject the config on reload (#21)
- Keybind recorder captured the shifted keysym (e.g. `exclam` for `Shift+1`) instead of the unshifted one Hyprland expects when `SHIFT` is in the modifier mask (#22)

## [0.1.0] - 2026-04-21

Initial release.

### Added

- Native GTK4/libadwaita settings app for Hyprland with live preview via IPC
- Config isolation — HyprMod writes only to its own `hyprland-gui.conf`; the user's `hyprland.conf` is never modified
- Undo/redo with Ctrl+Z
- Profiles — save, name, and share complete configurations as `.conf` files
- Config DNA — a unique visual fingerprint per profile
- Bezier curve editor with draggable control points, live animation preview, and a preset library
- Monitor configuration with per-monitor resolution, refresh rate, position, scale, transform, and mirroring. VRR, HDR, and 10-bit detection
- Keybind editor with modifier toggles, interactive key capture, and dispatcher selection
- Cursor theme picker with live previews
- Master, Dwindle, and Scrolling layout options
- Global search across all options (Ctrl+F) with highlight-pulse navigation
- Configurable config path and an auto-save toggle
- About dialog with version info and debug details
- Keyboard shortcuts overlay
- In-app link to report issues on GitHub
- Version-aware schema resolution — loads the option catalog matching the running Hyprland version, falling back to the bundled schema on mismatch
- Automatic migration of deprecated Hyprland syntax on save
- Desktop integration: application icon, `.desktop` file, and AppStream metainfo

[0.5.0]: https://github.com/BlueManCZ/hyprmod/releases/tag/v0.5.0
[0.4.0]: https://github.com/BlueManCZ/hyprmod/releases/tag/v0.4.0
[0.3.0]: https://github.com/BlueManCZ/hyprmod/releases/tag/v0.3.0
[0.2.0]: https://github.com/BlueManCZ/hyprmod/releases/tag/v0.2.0
[0.1.0]: https://github.com/BlueManCZ/hyprmod/releases/tag/v0.1.0
