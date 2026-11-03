"""Opt-in paired editor widgets. All real writes are explicit temporary E2E calls."""

import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from gi.repository import Adw, Gio, GLib
from hyprland_monitors import MonitorState
from hyprland_socket import HyprlandError

from hyprmod import main as main_module
from hyprmod.core import (
    bindings,
    config,
    editor_layout,
    installation,
    persistence,
    recovery,
    restoration,
    scoped_config,
    scoped_recovery,
    scoped_restore,
    source_bindings,
    transaction_publication,
)
from hyprmod.core.scopes import Scope
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
from hyprmod.window import HyprModWindow
from tests.test_scoped_review import evidence as evidence
from tests.test_scoped_review import snapshot
from tests.test_transaction_store import plan as plan

pytestmark = pytest.mark.skipif(
    os.environ.get("ATTUNE_GUI_SMOKE") != "1", reason="opt-in isolated Broadway widgets"
)

REAL_PUBLISH = transaction_publication.publish_reviewed


def wait_for(predicate):
    deadline = time.monotonic() + 15
    context = GLib.MainContext.default()
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    assert predicate()


@pytest.fixture(autouse=True)
def forbid_writes(monkeypatch):
    monkeypatch.setattr(
        bindings, "run_observe", MagicMock(side_effect=ValueError("Mock bindings read explicitly"))
    )
    for module, name in (
        (bindings, "persist_reviewed"),
        (source_bindings, "persist_reviewed"),
        (scoped_recovery, "commit_action"),
        (scoped_restore, "commit_restore"),
        (restoration, "commit_restore"),
        (recovery, "commit_recovery"),
        (persistence, "persist_reviewed"),
        (transaction_publication, "commit_recovery"),
    ):
        monkeypatch.setattr(
            module, name, MagicMock(side_effect=AssertionError("Unexpected real write API"))
        )
    monkeypatch.setattr(
        transaction_publication,
        "publish_reviewed",
        MagicMock(side_effect=AssertionError("Explicit temporary E2E publisher required")),
    )


@pytest.fixture
def window(plan, monkeypatch):
    def offline():
        raise HyprlandError("IPC disabled")

    monkeypatch.setattr("hyprland_socket.get_version", offline)
    monkeypatch.setattr(ScopeRecoveryPage, "ensure_loaded", lambda self: None)
    appearance_path = Path(plan.evidence.routes[0].file.path.resolved_path)
    original = scoped_config.read_document(appearance_path.read_text())
    assert isinstance(original, scoped_config.ScopedConfig)
    payload = original.payload()
    payload["values"] = {**dict(original.values), "decoration:future_option": "raw-string"}
    payload["animations"] = [*original.animations, "animation = future_animation, 0"]
    appearance_path.write_text(
        scoped_config.build_text(
            scoped_config.ScopedConfig(
                Scope.APPEARANCE,
                payload,
            )
        )
    )
    routes = []
    for route in plan.evidence.routes:
        lexical = Path(route.file.path.lexical_path)
        target = lexical.parent / "stow-target" / lexical.name
        target.parent.mkdir()
        lexical.rename(target)
        lexical.symlink_to(target)
        routes.append(installation.ScopeRoute(route.scope, str(lexical), str(target)))
    Path(plan.evidence.registry.path.lexical_path).write_text(
        installation.InstallationRegistry(*routes).to_json()
    )
    pair = editor_layout.inspect_entry(
        Path(plan.evidence.config_root), Path(plan.evidence.state_root)
    ).pair
    assert pair is not None
    application = Adw.Application(
        application_id=f"io.github.jdawson.Attune.PairTest{uuid4().hex}",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    application.register(None)
    sentinel = config.managed_path()
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("unread legacy sentinel")
    monkeypatch.setattr(
        config,
        "read_cached",
        MagicMock(side_effect=AssertionError("Paired construction must not read v1")),
    )
    widget = HyprModWindow(application=application, pair_layout=pair)
    yield widget
    wait_for(lambda: not widget._restore_in_progress)
    widget.destroy()
    application.quit()
    assert sentinel.read_text() == "unread legacy sentinel"


class TestPairEditor:
    def test_real_entry_opens_normal_paired_editor(self, plan, monkeypatch):
        def offline():
            raise HyprlandError("IPC disabled")

        monkeypatch.setattr("hyprland_socket.get_version", offline)
        monkeypatch.setattr(ScopeRecoveryPage, "ensure_loaded", lambda self: None)
        monkeypatch.setattr(main_module, "has_cairo_support", lambda: True)
        monkeypatch.setenv("XDG_CONFIG_HOME", plan.evidence.config_root)
        monkeypatch.setenv("XDG_STATE_HOME", plan.evidence.state_root)
        monkeypatch.setattr(
            config,
            "read_cached",
            MagicMock(side_effect=AssertionError("Paired startup must not read v1")),
        )
        application = main_module.HyprModApp()
        application.set_application_id(f"io.github.jdawson.Attune.PairEntry{uuid4().hex}")
        application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        application.register(None)
        application._integration_shown = True
        try:
            application.do_activate()
            wait_for(lambda: application._startup_cancel is None)
            editors = [w for w in application.get_windows() if isinstance(w, HyprModWindow)]
            assert len(editors) == 1
            assert editors[0].editor_mode == "pair-ready"
            assert editors[0].saved_values == {"general:border_size": "2"}
        finally:
            for widget in application.get_windows():
                if isinstance(widget, HyprModWindow) and widget._pending_page is not None:
                    widget._pending_page.cancel_review()
                widget.destroy()
            application.quit()

    def review(self, window):
        window.save()
        pending = window._pending_page
        assert pending is not None
        wait_for(lambda: pending._pair_review is not None)
        assert pending._save_button is not None
        assert pending._save_button.get_sensitive()
        return pending

    def test_projection_and_dirty_only_merge(self, window):
        pair = window.pair_layout
        assert pair is not None
        assert window.saved_values == dict(pair.appearance.values)
        assert window.saved_rules == []
        assert window.pair_proposals() == {}
        window._on_option_changed("general:border_size", 8)
        proposals = window.pair_proposals()
        assert tuple(proposals) == (Scope.APPEARANCE,)
        assert proposals[Scope.APPEARANCE].beziers == pair.appearance.beziers
        assert proposals[Scope.APPEARANCE].animations == pair.appearance.animations
        assert window._monitors_page is not None
        assert window._monitors_page.get_monitor_lines() == list(pair.displays.monitors)

    def test_two_real_saves_reopen_and_sibling_identity(self, window, monkeypatch):
        pair = window.pair_layout
        assert pair is not None
        before = snapshot(pair.evidence)

        def publish(plan, **kwargs):
            assert threading.current_thread() is not threading.main_thread()
            assert not threading.current_thread().daemon
            assert kwargs["config_root"] == Path(pair.evidence.config_root)
            assert kwargs["state_root"] == Path(pair.evidence.state_root)
            return REAL_PUBLISH(plan, **kwargs)

        monkeypatch.setattr(transaction_publication, "publish_reviewed", publish)
        for border in (8, 9):
            window._on_option_changed("general:border_size", border)
            pending = self.review(window)
            reviewed = pending._pair_review
            assert reviewed is not None and len(reviewed.scopes) == 2
            pending._on_save_reviewed(pending._save_button)
            wait_for(lambda: not window._restore_in_progress)
            assert not window._editor_invalidated
            assert not window.has_dirty()
            assert window.pair_layout is not None
            assert dict(window.pair_layout.appearance.values)["general:border_size"] == str(border)
            assert snapshot(window.pair_layout.evidence)[2] == before[2]
            assert (
                dict(window.pair_layout.appearance.values)["decoration:future_option"]
                == "raw-string"
            )
            assert window.pair_layout.appearance.beziers == pair.appearance.beziers
            assert window.pair_layout.appearance.animations == pair.appearance.animations
            assert all(Path(r.file.path.lexical_path).is_symlink() for r in pair.evidence.routes)
        reopened = editor_layout.run_entry(
            Path(pair.evidence.config_root), Path(pair.evidence.state_root)
        )
        assert reopened.mode == "pair-ready"
        assert reopened.pair is not None
        assert reopened.pair.appearance == window.pair_layout.appearance
        assert reopened.pair.displays == window.pair_layout.displays

    def test_noop_does_not_replace_outputs(self, window, monkeypatch):
        pair = window.pair_layout
        assert pair is not None
        before = snapshot(pair.evidence)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PUBLISH)
        pending = self.review(window)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window._editor_invalidated
        assert snapshot(pair.evidence) == before

    def test_invalid_result_retains_dirty_and_locks(self, window, monkeypatch):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", lambda *a, **k: object())
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert window._editor_invalidated and window.has_dirty()
        assert window.scope_may_have_changed and window.journal_may_have_changed

    @pytest.mark.parametrize(
        "result",
        [
            transaction_publication.PublicationResult(
                "a" * 32, "committed", cast(Any, 0), True, True
            ),
            transaction_publication.PublicationResult(None, "committed", False, True, True),
            transaction_publication.PublicationResult(None, "no-op", False, False, False),
            transaction_publication.PublicationResult(
                "invalid", "failed", True, True, True, "failed"
            ),
        ],
    )
    def test_invalid_result_fields(self, window, monkeypatch, result):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", lambda *a, **k: result)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert window._editor_invalidated and window.has_dirty()

    def test_thread_start_failure_releases_without_uncertainty(self, window, monkeypatch):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", MagicMock(side_effect=RuntimeError("start")))
            pending._on_save_reviewed(pending._save_button)
        assert window._restore_owner is None and not window._restore_in_progress
        assert not window._editor_invalidated and window.has_dirty()
        assert not window.scope_may_have_changed and not window.journal_may_have_changed

    def test_matching_success_after_external_goal_drift_locks(self, window, monkeypatch):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)

        def publish(plan, **kwargs):
            result = REAL_PUBLISH(plan, **kwargs)
            path = Path(plan.scopes[0].resolved_path)
            model = scoped_config.ScopedConfig(
                Scope.APPEARANCE,
                {
                    "values": {"general:border_size": "20"},
                    "beziers": [],
                    "animations": [],
                },
            )
            path.write_text(scoped_config.build_text(model))
            return result

        monkeypatch.setattr(transaction_publication, "publish_reviewed", publish)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert window._editor_invalidated and window.has_dirty()

    def test_cancelled_review_cannot_enable_save(self, window, monkeypatch):
        pending = self.review(window)
        pending.cancel_review()
        assert pending._pair_review is None
        assert pending._save_button is not None and not pending._save_button.get_sensitive()
        pending.refresh()
        assert pending._read_cancel is None

    def test_paired_evidence_is_expected_but_assessment_error_locks(self, window):
        window.scoped_evidence_discovered()
        assert not window._editor_invalidated
        recovery = window._scope_recovery_page
        assert recovery is not None and recovery.on_assessment_error is not None
        recovery.on_assessment_error("uninspectable")
        assert window._editor_invalidated

    def test_reset_and_undo_immediately_invalidate_review(self, window):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        window._on_undo()
        assert pending._pair_review is None
        assert pending._save_button is not None and not pending._save_button.get_sensitive()
        wait_for(lambda: pending._pair_review is not None)
        window._on_option_reset("general:border_size", None)
        assert pending._pair_review is None
        proposals = window.pair_proposals()
        assert "general:border_size" not in dict(proposals[Scope.APPEARANCE].values)
        assert dict(proposals[Scope.APPEARANCE].values)["decoration:future_option"] == "raw-string"

    def test_monitor_confirmation_blocks_save(self, window, monkeypatch):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        monitors = window._monitors_page
        assert monitors is not None
        monkeypatch.setattr(monitors, "is_confirm_pending", lambda: True)
        pending._on_save_reviewed(pending._save_button)
        assert not window._restore_in_progress and window.has_dirty()
        assert pending._pair_review is None

    def test_curve_edit_preserves_unknown_animation_and_unused_curves(self, window):
        pair = window.pair_layout
        assert pair is not None
        animations = window._animations_page
        assert animations is not None
        animations.restore_curve("z", (0.1, 0.2, 0.8, 0.9))
        proposals = window.pair_proposals()
        assert proposals[Scope.APPEARANCE].animations == pair.appearance.animations
        assert "bezier = unused, 0, 0, 1, 1" in proposals[Scope.APPEARANCE].beziers

    def test_postsave_refresh_failure_never_marks_saved(self, window, monkeypatch):
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PUBLISH)
        monkeypatch.setattr(
            editor_layout, "run_entry", MagicMock(side_effect=ValueError("offline"))
        )
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert window._editor_invalidated and window.has_dirty()
        assert window.scope_may_have_changed and window.journal_may_have_changed

    @pytest.mark.parametrize("drift", ["data", "foreign", "registry", "link"])
    def test_external_drift_refuses_reviewed_save(self, window, monkeypatch, drift):
        pair = window.pair_layout
        assert pair is not None
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        toasts = []
        monkeypatch.setattr(window, "show_toast", lambda message, *a, **k: toasts.append(message))
        path = Path(pair.evidence.routes[0].file.path.resolved_path)
        if drift == "data":
            path.write_text(path.read_text() + "-- external edit\n")
        elif drift == "foreign":
            path.write_text("-- hand-authored foreign Lua\n")
        elif drift == "registry":
            registry = Path(pair.evidence.registry.path.resolved_path)
            registry.write_text(registry.read_text() + "\n")
        else:
            lexical = Path(pair.evidence.routes[0].file.path.lexical_path)
            target = path.parent / "other" / path.name
            target.parent.mkdir()
            target.write_bytes(path.read_bytes())
            lexical.unlink()
            lexical.symlink_to(target)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PUBLISH)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert window.has_dirty() and not window._editor_invalidated
        assert window.pair_layout is pair
        refusal = toasts[-1]
        window._on_save()
        wait_for(lambda: pending._read_cancel is None and not pending._refresh_pending)
        assert pending._pair_review is None
        assert pending._save_button is not None and not pending._save_button.get_sensitive()
        assert pending._review_error is not None and pending._review_error.get_visible()
        for text in (
            "Session-local edits retained",
            "cannot adopt external edits",
            "manually correct or restore",
            "registered canonical files/routes",
            "restart/reopen Attune",
        ):
            assert text in refusal
            assert text in pending._review_error.get_text()
        assert window.has_dirty() and window.pair_layout is pair

    def test_real_monitor_model_save_reopen_preserves_disconnected(self, window, monkeypatch):
        pair = window.pair_layout
        if pair is None or window._monitors_page is None:
            pytest.fail("Expected paired monitor editor")
        monitors = window._monitors_page
        monitor = MonitorState(
            name="DP-9",
            make="Acme",
            model="Pixel",
            width=1920,
            height=1080,
            refresh_rate=60.0,
            x=0,
            y=0,
            scale=1.0,
        )
        offline = MagicMock()
        offline.monitors.get_all.return_value = [monitor]
        offline.monitors.apply.side_effect = HyprlandError("IPC disabled")
        monkeypatch.setattr(window, "hypr", offline)
        monkeypatch.setattr("hyprmod.pages.monitors.page.get_monitor_capabilities", lambda name: {})
        monitors.reload_from_saved()
        assert not monitors.is_dirty()
        monitors.restore_snapshot([replace(monitor, scale=2.0)], {"DP-9"})
        assert monitors.is_dirty()
        lines = monitors.get_monitor_lines()
        assert lines != list(pair.displays.monitors)
        assert "monitor = HDMI-A-9, disable" in lines
        assert any(line.startswith("monitor = DP-9,") and line.endswith(", 2") for line in lines)
        before = snapshot(pair.evidence)
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PUBLISH)
        pending = self.review(window)
        assert pending._pair_review is not None
        assert pending._pair_review.changed_scopes == (Scope.DISPLAYS,)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window._editor_invalidated and not window.has_dirty()
        assert snapshot(pair.evidence)[1] == before[1]
        entry = editor_layout.run_entry(
            Path(pair.evidence.config_root), Path(pair.evidence.state_root)
        )
        assert entry.mode == "pair-ready" and entry.pair is not None
        assert entry.pair.displays.monitors == tuple(lines)
        reopened = HyprModWindow(application=window.get_application(), pair_layout=entry.pair)
        try:
            assert reopened._monitors_page is not None
            assert reopened._monitors_page.get_monitor_lines() == lines
            assert not reopened.has_dirty()
        finally:
            if reopened._pending_page is not None:
                reopened._pending_page.cancel_review()
            reopened.destroy()

    def test_display_only_and_both_scope_saves(self, window, monkeypatch):
        pair = window.pair_layout
        assert pair is not None
        monitors = window._monitors_page
        assert monitors is not None
        lines = [*pair.displays.monitors, "monitor = DP-10, disable"]
        monkeypatch.setattr(
            monitors, "is_dirty", lambda: lines != list(window.saved_sections["monitor"])
        )
        monkeypatch.setattr(monitors, "get_monitor_lines", lambda: lines.copy())
        monkeypatch.setattr(transaction_publication, "publish_reviewed", REAL_PUBLISH)
        before = snapshot(pair.evidence)
        pending = self.review(window)
        assert pending._pair_review is not None
        assert pending._pair_review.changed_scopes == (Scope.DISPLAYS,)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window._editor_invalidated and not window.has_dirty()
        assert snapshot(pair.evidence)[1] == before[1]
        lines.append("monitor = DP-11, disable")
        window._on_option_changed("general:border_size", 9)
        pending = self.review(window)
        assert pending._pair_review is not None
        assert pending._pair_review.changed_scopes == tuple(Scope)
        assert all(review.diff for review in pending._pair_review.scopes)
        pending._on_save_reviewed(pending._save_button)
        wait_for(lambda: not window._restore_in_progress)
        assert not window._editor_invalidated and not window.has_dirty()

    def test_writer_ownership_close_and_backup_finish(self, window, monkeypatch):
        entered = threading.Event()
        release = threading.Event()

        def publish(*args, **kwargs):
            entered.set()
            release.wait(10)
            return transaction_publication.PublicationResult(
                None, "failed", False, False, False, "refused"
            )

        monkeypatch.setattr(transaction_publication, "publish_reviewed", publish)
        window._on_option_changed("general:border_size", 8)
        pending = self.review(window)
        try:
            pending._on_save_reviewed(pending._save_button)
            assert entered.wait(3)
            assert window._on_close_request()
            window.finish_restore(False)
            assert window._restore_owner == "save" and window._restore_in_progress
            with pytest.raises(ValueError):
                window.scope_restore_permission()
        finally:
            release.set()
        wait_for(lambda: not window._restore_in_progress)
        assert not window._editor_invalidated and window.has_dirty()

    def test_edit_invalidates_inflight_review(self, window, monkeypatch):
        entered = threading.Event()
        release = threading.Event()
        original = editor_layout.run_prepare_review

        def prepare(pair, proposals, **kwargs):
            entered.set()
            release.wait(10)
            return original(pair, proposals)

        monkeypatch.setattr(editor_layout, "run_prepare_review", prepare)
        window._on_option_changed("general:border_size", 8)
        window.save()
        pending = window._pending_page
        assert pending is not None
        try:
            wait_for(entered.is_set)
            window._on_option_changed("general:border_size", 9)
            assert pending._pair_review is None
            assert pending._save_button is not None and not pending._save_button.get_sensitive()
        finally:
            release.set()
        wait_for(lambda: pending._pair_review is not None)
        review = pending._pair_review
        assert review is not None
        model = scoped_config.read_document(review.scopes[0].proposed_text)
        assert isinstance(model, scoped_config.ScopedConfig)
        assert dict(model.values)["general:border_size"] == "9"
