"""Sharing uses a projection, never the collector's raw strings."""

from hyprmod.core.diagnostics import build_diagnostics_report
from hyprmod.core.health import HealthCheck, HealthSnapshot


class TestDiagnostics:
    def test_seven_checks_counts_version_and_caveats(self):
        summaries = {
            "compositor": "Hyprland v0.55.1 (reachable)",
            "config_errors": "2 configuration errors reported",
            "displays": "3 connected displays reported",
            "output": "Owned Attune output",
            "validator": "Lua validator found (not invoked)",
            "backups": "4 regular hash-named backup candidates",
            "drift": "1 matching, 2 differing, 3 unknown saved scalar options",
        }
        snapshot = HealthSnapshot(
            "2026-10-26T12:00:00+00:00",
            tuple(
                HealthCheck(key, "Untrusted title", "available", summary, ("secret detail",))
                for key, summary in summaries.items()
            ),
        )
        report = build_diagnostics_report(snapshot)
        assert all(summary in report for summary in summaries.values())
        assert "Untrusted title" not in report
        assert "secret detail" not in report
        assert "Observation: 2026-10-26T12:00:00+00:00" in report
        assert "does not establish runtime loading" in report
        assert "not validated as restorable" in report
        assert "inspect before sharing" in report
        assert "not guaranteed to remove all identifying details" in report
        assert build_diagnostics_report(snapshot) == report

    def test_all_raw_strings_are_omitted_including_quoted_paths_and_secrets(self):
        secret = (
            'Permission denied: "/home/Jane Doe/private file.lua" '
            "'/srv/private user/secret.lua' C:\\Users\\Jane Doe\\secret.lua "
            "https://user:token@example.test/api exec = password SERIAL123 <b>&"
        )
        for status in ("available", "unavailable", "unknown", "failed"):
            snapshot = HealthSnapshot(
                "2026-10-26T12:00:00+00:00",
                tuple(
                    HealthCheck(key, secret, status, secret, (secret,))
                    for key in (
                        "compositor",
                        "config_errors",
                        "displays",
                        "output",
                        "validator",
                        "backups",
                        "drift",
                        "unknown-secret",
                    )
                ),
            )
            report = build_diagnostics_report(snapshot)
            for token in ("Jane", "srv", "token", "password", "SERIAL123", "<b>", "example"):
                assert token not in report
            assert len(report) < 2500

    def test_stale_timestamp_and_invalid_time(self):
        snapshot = HealthSnapshot("2026-10-26T12:00:00+00:00", ())
        assert "Observation: STALE - 2026-10-26T12:00:00+00:00" in build_diagnostics_report(
            snapshot, stale=True
        )
        assert "Observation: Unavailable" in build_diagnostics_report(
            HealthSnapshot("secret timestamp\n/path", ())
        )

    def test_failed_summaries_only_allow_counts_and_patterns_are_full_matches(self):
        snapshot = HealthSnapshot(
            "2026-10-26T12:00:00+00:00",
            (
                HealthCheck("config_errors", "", "failed", "5 configuration errors reported"),
                HealthCheck("output", "", "failed", "Owned Attune output"),
                HealthCheck("displays", "", "available", "2 connected displays reported\nsecret"),
                HealthCheck("compositor", "", "available", "Hyprland v0.55.1-secret (reachable)"),
                HealthCheck(
                    "drift",
                    "",
                    "unknown",
                    "1 matching, 2 differing, 3 unknown saved scalar options; "
                    "partial observation (time/query budget exhausted)",
                ),
            ),
        )
        report = build_diagnostics_report(snapshot)
        assert "5 configuration errors reported" in report
        assert "Owned Attune output" not in report
        assert "connected displays reported" not in report
        assert "secret" not in report
        assert "partial observation (time/query budget exhausted)" in report
