"""Tests for scripts/audit_memory_store.py — CLI flags and dry-run safety.

The operational memory store is mocked; no real database is required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.audit_memory_store as ams


# -- Helpers ------------------------------------------------------------------

def _make_store(items: list | None = None) -> MagicMock:
    store = MagicMock()
    store.search.return_value = items or []
    return store


# -- --dry-run flag acceptance ------------------------------------------------

class TestDryRunFlag:
    def test_dry_run_flag_accepted(self) -> None:
        """--dry-run must be parsed without error."""
        store = _make_store()
        with patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store):
            rc = ams.main(["--dry-run"])
        assert rc == 0

    def test_dry_run_sets_dry_run_true(self) -> None:
        """--dry-run must produce a report with dry_run=True."""
        store = _make_store()
        reports: list[ams.AuditReport] = []

        original_audit = ams.audit

        def _capture_audit(s, *, apply, scan_duplicates=True):
            report = original_audit(s, apply=apply, scan_duplicates=scan_duplicates)
            reports.append(report)
            return report

        with (
            patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store),
            patch("scripts.audit_memory_store.audit", side_effect=_capture_audit),
        ):
            ams.main(["--dry-run"])

        assert reports, "audit() was not called"
        assert reports[0].dry_run is True

    def test_no_flags_is_dry_run(self) -> None:
        """Default (no flags) must also be read-only."""
        store = _make_store()
        reports: list[ams.AuditReport] = []

        original_audit = ams.audit

        def _capture(s, *, apply, scan_duplicates=True):
            r = original_audit(s, apply=apply, scan_duplicates=scan_duplicates)
            reports.append(r)
            return r

        with (
            patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store),
            patch("scripts.audit_memory_store.audit", side_effect=_capture),
        ):
            ams.main([])

        assert reports[0].dry_run is True

    def test_dry_run_does_not_call_apply(self) -> None:
        """--dry-run must never trigger the apply path (no store.add calls)."""
        store = _make_store()
        with patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store):
            ams.main(["--dry-run"])

        store.add.assert_not_called()

    def test_dry_run_and_apply_together_stays_dry(self) -> None:
        """--dry-run takes precedence over --apply when both are given."""
        store = _make_store()
        reports: list[ams.AuditReport] = []

        original_audit = ams.audit

        def _capture(s, *, apply, scan_duplicates=True):
            r = original_audit(s, apply=apply, scan_duplicates=scan_duplicates)
            reports.append(r)
            return r

        with (
            patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store),
            patch("scripts.audit_memory_store.audit", side_effect=_capture),
        ):
            ams.main(["--dry-run", "--apply"])

        assert reports[0].dry_run is True, "--dry-run must override --apply"


# -- --apply flag behaviour ---------------------------------------------------

class TestApplyFlag:
    def test_apply_flag_accepted(self) -> None:
        """--apply must be accepted without parsing error."""
        store = _make_store()
        with patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store):
            rc = ams.main(["--apply"])
        assert rc == 0

    def test_apply_sets_dry_run_false(self) -> None:
        """--apply alone must produce a report with dry_run=False."""
        store = _make_store()
        reports: list[ams.AuditReport] = []

        original_audit = ams.audit

        def _capture(s, *, apply, scan_duplicates=True):
            r = original_audit(s, apply=apply, scan_duplicates=scan_duplicates)
            reports.append(r)
            return r

        with (
            patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store),
            patch("scripts.audit_memory_store.audit", side_effect=_capture),
        ):
            ams.main(["--apply"])

        assert reports[0].dry_run is False


# -- Output includes mode label -----------------------------------------------

class TestModeOutput:
    def _run_capture(self, argv: list[str]) -> str:
        store = _make_store()
        lines: list[str] = []
        with (
            patch("scripts.audit_memory_store.get_operational_memory_store", return_value=store),
            patch("scripts.audit_memory_store._stdout", side_effect=lambda s: lines.append(s)),
        ):
            ams.main(argv)
        return "\n".join(lines)

    def test_dry_run_output_mentions_dry_run(self) -> None:
        output = self._run_capture(["--dry-run"])
        assert "dry-run" in output.lower()

    def test_default_output_mentions_dry_run(self) -> None:
        output = self._run_capture([])
        assert "dry-run" in output.lower()

    def test_apply_output_mentions_apply(self) -> None:
        output = self._run_capture(["--apply"])
        assert "apply" in output.lower() or "pruned" in output.lower()
