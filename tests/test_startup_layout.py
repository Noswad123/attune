"""Startup orchestration without GTK construction, IPC, or real user files."""

import threading
from threading import Thread
from types import MethodType, SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from hyprmod import main
from hyprmod.core.editor_layout import CanonicalPairLayout, EditorEntry
from hyprmod.core.scoped_recovery import LayoutAssessment
from tests.test_scoped_review import appearance, displays
from tests.test_scoped_review import evidence as evidence


@pytest.fixture
def startup(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for name in ("ApplicationWindow", "ToolbarView", "HeaderBar", "WindowTitle"):
        monkeypatch.setattr(main.Adw, name, MagicMock())
    for name in ("Stack", "Button"):
        monkeypatch.setattr(main.Gtk, name, MagicMock())
    for name in ("EmptyState", "HealthPage", "BackupsPage", "ScopeRecoveryPage"):
        monkeypatch.setattr(main, name, MagicMock())
    app = MagicMock()
    app._startup_cancel = None
    app._config_error_window = None
    app._recovery_backups = None
    for name in ("do_activate", "_check_startup", "_dismiss_config_error"):
        setattr(app, name, MethodType(getattr(main.HyprModApp, name), app))
    pending = []
    threads = []
    monkeypatch.setattr(
        main.GLib, "idle_add", lambda callback, *args: pending.append((callback, args))
    )
    thread_factory = MagicMock(side_effect=lambda **kwargs: threads.append(kwargs) or MagicMock())
    monkeypatch.setattr(main.threading, "Thread", thread_factory)
    probe = MagicMock()
    monkeypatch.setattr(main.editor_layout, "run_entry", probe)
    monkeypatch.setattr(
        main.scoped_recovery,
        "run_assess",
        MagicMock(side_effect=AssertionError("Old startup gate")),
    )
    return SimpleNamespace(app=app, pending=pending, threads=threads, probe=probe, root=tmp_path)


def entry(startup, mode="legacy-clear", pair=None):
    return EditorEntry(
        str(startup.root / "config"),
        str(startup.root / "state"),
        mode,
        pair,
        "Manual remediation required" if mode == "blocked" else None,
    )


@pytest.fixture
def pair(evidence):
    return CanonicalPairLayout(evidence, appearance(), displays())


def assessment(startup, mode="legacy-clear"):
    return LayoutAssessment(
        str(startup.root / "config"),
        str(startup.root / "state"),
        mode,
        "absent",
        (),
        None,
        (),
        False,
        ("uninspectable",) if mode == "blocked" else (),
    )


class TestStartupGate:
    def test_probe_is_off_gtk_before_editor_and_activation_is_coalesced(self, startup):
        app = startup.app
        startup.probe.return_value = entry(startup)
        app.do_activate()
        app.do_activate()
        app._check_startup()
        assert len(startup.threads) == 1
        assert startup.threads[0]["daemon"] is False
        app._open_editor.assert_not_called()
        startup.probe.assert_not_called()
        main_thread = threading.get_ident()
        observed = []
        startup.probe.side_effect = lambda *args, **kwargs: (
            observed.append(threading.get_ident()) or entry(startup)
        )
        # The captured target is run on a real worker; idle completion stays queued.
        worker = Thread(target=startup.threads[0]["target"])
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(observed) == 1 and observed[0] != main_thread
        app._open_editor.assert_not_called()
        startup.probe.assert_called_once_with(
            startup.root / "config",
            startup.root / "state",
            cancel_event=app._startup_cancel,
            timeout=30,
        )
        callback, args = startup.pending.pop()
        callback(*args)
        callback(*args)
        app._open_editor.assert_called_once_with()
        app._show_config_error.assert_not_called()
        assert not (startup.root / "state").exists()
        assert not (startup.root / "config").exists()

    def test_pair_ready_dispatches_same_pair_without_old_recovery_gate(self, startup, pair):
        startup.probe.return_value = entry(startup, "pair-ready", pair)
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_called_once_with(pair)
        assert startup.app._open_editor.call_args.args[0] is pair
        startup.app._show_config_error.assert_not_called()
        assert not (startup.root / "state").exists()

    def test_blocked_entry_uses_backend_reason(self, startup):
        startup.probe.return_value = entry(startup, "blocked")
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once_with("Manual remediation required")

    @pytest.mark.parametrize("mode", ["legacy-clear", "pair-ready", "blocked", "unknown"])
    def test_wrong_dto_never_opens_editor(self, startup, mode):
        startup.probe.return_value = SimpleNamespace(mode=mode)
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once()

    def test_old_clear_assessment_is_not_editor_authority(self, startup):
        startup.probe.return_value = assessment(startup)
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once()

    def test_worker_start_error_fails_closed(self, startup, monkeypatch):
        monkeypatch.setattr(main.threading.Thread, "side_effect", RuntimeError("Cannot start"))
        startup.app.do_activate()
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once_with("Cannot start")
        assert startup.app._startup_cancel is None
        startup.probe.assert_not_called()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("mode", "unknown"),
            ("config_root", "/other-config"),
            ("state_root", "/other-state"),
            ("pair", SimpleNamespace()),
            ("message", "unexpected"),
        ],
    )
    def test_wrong_entry_context_fails_closed(self, startup, field, value):
        result = entry(startup)
        object.__setattr__(result, field, value)
        startup.probe.return_value = result
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once()

    @pytest.mark.parametrize("root", ["config_root", "state_root"])
    def test_pair_evidence_from_other_roots_fails_closed(self, startup, pair, root):
        result = entry(startup, "pair-ready", pair)
        object.__setattr__(pair.evidence, root, "/other-root")
        startup.probe.return_value = result
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once()

    @pytest.mark.parametrize("error", [TimeoutError("timeout"), ValueError("bad DTO")])
    def test_worker_errors_fail_closed(self, startup, error):
        startup.probe.side_effect = error
        startup.app.do_activate()
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        startup.app._open_editor.assert_not_called()
        startup.app._show_config_error.assert_called_once_with(str(error))

    def test_close_cancels_and_stale_completion_cannot_replace_new_gate(self, startup):
        app = startup.app
        startup.probe.return_value = entry(startup)
        app.do_activate()
        checking = app._config_error_window
        cancel = app._startup_cancel
        startup.threads[0]["target"]()
        handlers = {call.args[0]: call.args[1] for call in checking.connect.call_args_list}
        assert handlers["close-request"]() is False
        assert cancel.is_set()
        app.do_activate()
        newer = app._startup_cancel
        callback, args = startup.pending.pop()
        callback(*args)
        assert app._startup_cancel is newer
        app._open_editor.assert_not_called()
        app._show_config_error.assert_not_called()
        startup.threads[1]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        app._open_editor.assert_called_once_with()

    def test_legacy_read_error_keeps_old_shell_until_replacement(self, startup, monkeypatch):
        app = startup.app
        app._integration_shown = True
        old = MagicMock()
        app._config_error_window = old
        app.get_windows.return_value = [old]

        # Use a type for the isinstance boundary and a failing constructor.
        class FailedEditor:
            def __init__(self, **kwargs):
                assert not old.destroy.called
                raise ValueError("foreign output")

        monkeypatch.setattr(main, "HyprModWindow", FailedEditor)
        main.HyprModApp._open_editor(app)
        app._show_config_error.assert_called_once_with("foreign output")
        old.destroy.assert_not_called()

    def test_clear_continuation_constructs_editor_before_dismissing_shell(
        self, startup, monkeypatch
    ):
        app = startup.app
        app._integration_shown = False
        app._config_error_window = MagicMock()
        old = app._config_error_window
        created = []

        class Editor:
            def __init__(self, **kwargs):
                assert app._config_error_window is old
                assert kwargs == {"application": app}
                created.append(self)
                self.present = MagicMock()

        monkeypatch.setattr(main, "HyprModWindow", Editor)
        monkeypatch.setattr(main, "has_cairo_support", lambda: True)
        onboarding = MagicMock()
        monkeypatch.setattr(main, "OnboardingDialog", onboarding)
        main.HyprModApp._open_editor(app)
        assert len(created) == 1
        created[0].present.assert_called_once_with()
        old.destroy.assert_called_once_with()
        onboarding.return_value.present.assert_called_once_with(created[0])
        assert app._integration_shown is True

    @pytest.mark.parametrize("cairo", [True, False])
    def test_pair_constructor_skips_legacy_onboarding_and_read(
        self, startup, pair, monkeypatch, cairo
    ):
        app = startup.app
        app._integration_shown = False
        created = []

        class Editor:
            def __init__(self, *, application, pair_layout):
                assert application is app
                assert pair_layout is pair
                old.destroy.assert_not_called()
                self.present = MagicMock()
                created.append(self)

        monkeypatch.setattr(main, "HyprModWindow", Editor)
        monkeypatch.setattr(main, "has_cairo_support", lambda: cairo)
        onboarding = MagicMock()
        alert = MagicMock()
        monkeypatch.setattr(main, "OnboardingDialog", onboarding)
        monkeypatch.setattr(main.Adw, "AlertDialog", alert)
        legacy_read = MagicMock(side_effect=AssertionError("Legacy reader used"))
        monkeypatch.setattr(main.config, "read_cached", legacy_read)
        monkeypatch.setattr(main.config, "read_all_sections", legacy_read)
        startup.probe.return_value = entry(startup, "pair-ready", pair)
        expensive = MagicMock(side_effect=AssertionError("Pair revalidated on GTK"))
        monkeypatch.setattr(CanonicalPairLayout, "__post_init__", expensive)
        monkeypatch.setattr(CanonicalPairLayout, "to_json", expensive)
        app._open_editor = MethodType(main.HyprModApp._open_editor, app)
        app.do_activate()
        old = app._config_error_window
        startup.threads[0]["target"]()
        callback, args = startup.pending.pop()
        callback(*args)
        assert len(created) == 1
        created[0].present.assert_called_once_with()
        onboarding.assert_not_called()
        legacy_read.assert_not_called()
        expensive.assert_not_called()
        assert alert.call_count == (0 if cairo else 1)
        assert app._integration_shown is False

    @pytest.mark.parametrize("owner", ["scope", "backups"])
    def test_writer_vetoes_retry_and_activation(self, startup, owner):
        shell = MagicMock(spec=main.RecoveryWindow)
        shell.restore_writing = True
        shell._restore_owner = owner
        startup.app._config_error_window = shell
        startup.app.do_activate()
        startup.app._check_startup()
        assert shell.present.call_count == 2
        assert startup.threads == []
        startup.app._open_editor.assert_not_called()


class TestRecoveryWriters:
    @pytest.mark.parametrize("owner,other", [("scope", "backups"), ("backups", "scope")])
    @pytest.mark.parametrize("cache_error", [False, True])
    def test_owner_exclusion_and_refused_finish(self, owner, other, monkeypatch, cache_error):
        # Property semantics without constructing a GTK window.
        class Owner:
            restore_writing = main.RecoveryWindow.restore_writing
            restore_permission = main.RecoveryWindow.restore_permission
            begin_restore = main.RecoveryWindow.begin_restore
            finish_restore = main.RecoveryWindow.finish_restore
            _restore_owner = None

        window = Owner()

        def clear_cache():
            assert not window.restore_writing
            window.begin_restore(other)
            if cache_error:
                raise RuntimeError("cache failed")

        invalidate = MagicMock(side_effect=clear_cache)
        monkeypatch.setattr(main, "config", SimpleNamespace(invalidate_cache=invalidate))
        window.begin_restore(owner)
        with pytest.raises(ValueError, match="owns"):
            window.begin_restore(other)
        window.finish_restore(other, True)
        assert window.restore_writing
        invalidate.assert_not_called()
        if cache_error:
            with pytest.raises(RuntimeError, match="cache failed"):
                window.finish_restore(owner, True)
        else:
            window.finish_restore(owner, True)
        assert window._restore_owner == other
        invalidate.assert_called_once_with()
        window.finish_restore(owner, False)
        assert window._restore_owner == other
        window.finish_restore(other, False)
        assert not window.restore_writing
        window.begin_restore("scope")
        window.finish_restore("scope", False)

    def test_shell_integrates_scope_without_automatic_reads(self, startup, monkeypatch):
        shell = MagicMock()
        monkeypatch.setattr(main, "RecoveryWindow", MagicMock(return_value=shell))
        startup.app._dismiss_config_error = MagicMock()
        result = assessment(startup, "blocked")
        main.HyprModApp._show_config_error(startup.app, "blocked", assessment=result)
        scope = cast(MagicMock, main.ScopeRecoveryPage).return_value
        scope.build.assert_called_once()
        scope.seed_assessment.assert_called_once_with(result)
        scope.ensure_loaded.assert_not_called()
        backups = cast(MagicMock, main.BackupsPage)
        backups.return_value.ensure_loaded.assert_not_called()
        scoped = cast(MagicMock, main.ScopeRecoveryPage).call_args.kwargs
        legacy = backups.call_args.kwargs
        scoped["begin_restore"]()
        shell.begin_restore.assert_called_once_with("scope")
        legacy["finish_restore"](False)
        shell.finish_restore.assert_called_once_with("backups", False)
        scoped["finish_restore"](True)
        assert shell.finish_restore.call_args.args == ("scope", True)
        assert startup.app._config_error_window is shell
        callback = scope.on_assessment
        callback(assessment(startup))
        startup.app._open_editor.assert_not_called()
