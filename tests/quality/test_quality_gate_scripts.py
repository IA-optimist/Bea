from __future__ import annotations

import json
from pathlib import Path


def test_silent_except_detector_flags_exception_pass(tmp_path: Path) -> None:
    from scripts.check_silent_except_baseline import scan_silent_except_counts

    bad = tmp_path / "bad.py"
    bad.write_text(
        "try:\n"
        "    risky()\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )

    assert scan_silent_except_counts(tmp_path) == {"bad.py": 1}


def test_silent_except_detector_allows_clean_file(tmp_path: Path) -> None:
    from scripts.check_silent_except_baseline import scan_silent_except_counts

    clean = tmp_path / "clean.py"
    clean.write_text(
        "try:\n"
        "    risky()\n"
        "except Exception as exc:\n"
        "    log.warning('risky_failed', exc_info=exc)\n",
        encoding="utf-8",
    )

    assert scan_silent_except_counts(tmp_path) == {}


def test_silent_except_baseline_reports_stable_counts() -> None:
    from scripts.check_silent_except_baseline import compare_to_baseline

    baseline = {"files": {"legacy.py": 2}}

    assert compare_to_baseline({"legacy.py": 2}, baseline) == []
    assert compare_to_baseline({"legacy.py": 3}, baseline) == [("legacy.py", 2, 3)]


def test_quality_marker_counter_counts_quarantine_xfail_and_stale(tmp_path: Path) -> None:
    from scripts.check_test_marker_baseline import scan_marker_counts

    test_file = tmp_path / "test_legacy.py"
    test_file.write_text(
        "import pytest\n\n"
        "@pytest.mark.quarantine\n"
        "def test_quarantined():\n"
        "    pass\n\n"
        "@pytest.mark.xfail(reason='legacy')\n"
        "def test_expected_failure():\n"
        "    pass\n\n"
        "@pytest.mark.stale\n"
        "def test_stale():\n"
        "    pass\n",
        encoding="utf-8",
    )

    assert scan_marker_counts(tmp_path) == {"quarantine": 1, "xfail": 1, "stale": 1}


def test_quality_marker_baseline_reports_regression() -> None:
    from scripts.check_test_marker_baseline import compare_marker_counts

    baseline = {"markers": {"quarantine": 2, "xfail": 4, "stale": 0}}
    actual = {"quarantine": 3, "xfail": 3, "stale": 0}

    assert compare_marker_counts(actual, baseline) == [("quarantine", 2, 3)]


def test_coverage_threshold_parser_reads_ci_fail_under() -> None:
    from scripts.check_coverage_threshold import extract_coverage_fail_under

    ci_text = 'COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-60}"\n'

    assert extract_coverage_fail_under(ci_text) == 60


def test_coverage_threshold_baseline_reports_lowered_threshold() -> None:
    from scripts.check_coverage_threshold import compare_coverage_threshold

    assert compare_coverage_threshold(60, {"min_fail_under": 60}) is None
    assert compare_coverage_threshold(55, {"min_fail_under": 60}) == (60, 55)


def test_validate_local_quick_summary_without_crash(monkeypatch, capsys) -> None:
    import scripts.validate_local as validate_local

    calls: list[str] = []

    def fake_run(name: str, cmd: list[str], *, cwd=validate_local.PROJECT_ROOT) -> int:
        calls.append(name)
        return 0

    monkeypatch.setattr(validate_local, "_run", fake_run)
    monkeypatch.setattr(validate_local, "_has_module", lambda module: False)
    monkeypatch.setattr(validate_local.subprocess, "run", lambda *args, **kwargs: type("P", (), {"returncode": 0})())

    assert validate_local.main(["--quick"]) == 0

    output = capsys.readouterr().out
    assert "VALIDATION SUMMARY" in output
    assert "ruff: PASS" in output
    assert "except/pass ratchet: PASS" in output
    assert "coverage threshold: PASS" in output
    assert "build wheel" not in calls


def test_baseline_json_examples_are_parseable(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"files": {"legacy.py": 1}}), encoding="utf-8")

    assert json.loads(baseline.read_text(encoding="utf-8"))["files"]["legacy.py"] == 1
