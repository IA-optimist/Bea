"""Tests for scripts/release_check.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
VENV_PYTHON = str(Path(sys.executable))


def _load_module(tmp_path: Path | None = None):
    spec = importlib.util.spec_from_file_location(
        "release_check", ROOT / "scripts" / "release_check.py"
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if tmp_path is not None:
        mod.ROOT = tmp_path
    return mod


def _run_json(*extra_args: str) -> dict:
    result = subprocess.run(
        [VENV_PYTHON, str(ROOT / "scripts" / "release_check.py"), "--json", *extra_args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Integration tests (against real repo)
# ---------------------------------------------------------------------------


def test_release_check_runs_without_crash():
    report = _run_json()
    assert "overall_status" in report
    assert "version" in report
    assert "checks" in report


def test_overall_status_is_valid():
    report = _run_json()
    assert report["overall_status"] in ("pass", "pending", "fail")


def test_version_not_unknown():
    report = _run_json()
    assert report["version"] != "unknown"


def test_version_file_present():
    assert (ROOT / "VERSION").exists(), "VERSION file must exist for dev-preview release"


def test_changelog_check_passes():
    report = _run_json()
    ch = next((c for c in report["checks"] if "Changelog" in c["check"]), None)
    assert ch is not None
    assert ch["status"] == "pass"


def test_release_notes_check_passes():
    report = _run_json()
    rn = next((c for c in report["checks"] if "Release notes" in c["check"]), None)
    assert rn is not None
    assert rn["status"] == "pass"


def test_env_example_check_passes():
    report = _run_json()
    env_c = next((c for c in report["checks"] if "Environment" in c["check"]), None)
    assert env_c is not None
    assert env_c["status"] == "pass"


def test_json_output_is_stable():
    report = _run_json()
    # Must be round-trippable
    json.dumps(report)
    assert isinstance(report["checks"], list)
    assert all("check" in c and "status" in c and "message" in c for c in report["checks"])


# ---------------------------------------------------------------------------
# Unit tests (monkeypatching ROOT)
# ---------------------------------------------------------------------------


def test_env_example_with_real_secret_fails(tmp_path):
    env = tmp_path / ".env.example"
    env.write_text("OPENROUTER_API_KEY=sk-or-v1-abc123def456ghi789jkl012mno345pqr678stu\n")
    mod = _load_module(tmp_path)
    result = mod.check_no_secrets_in_env_example()
    assert result["status"] == "fail"


def test_env_example_with_placeholder_passes(tmp_path):
    env = tmp_path / ".env.example"
    env.write_text("OPENROUTER_API_KEY=<YOUR_OPENROUTER_API_KEY>\n")
    mod = _load_module(tmp_path)
    result = mod.check_no_secrets_in_env_example()
    assert result["status"] == "pass"


def test_env_example_missing_skipped(tmp_path):
    mod = _load_module(tmp_path)
    result = mod.check_no_secrets_in_env_example()
    assert result["status"] == "skip"


def test_production_ready_bare_claim_warns(tmp_path):
    (tmp_path / "RELEASE_NOTES.md").write_text("This is production ready for everyone.\n")
    mod = _load_module(tmp_path)
    result = mod.check_not_production_ready()
    assert result["status"] == "warning"


def test_not_production_ready_phrase_passes(tmp_path):
    (tmp_path / "RELEASE_NOTES.md").write_text("This is NOT production ready.\n")
    mod = _load_module(tmp_path)
    result = mod.check_not_production_ready()
    assert result["status"] == "pass"


def test_missing_required_file_fails(tmp_path):
    mod = _load_module(tmp_path)
    result = mod.check_file_exists("VERSION", "Version file")
    assert result["status"] == "fail"


def test_present_required_file_passes(tmp_path):
    (tmp_path / "VERSION").write_text("0.1.0-dev-preview\n")
    mod = _load_module(tmp_path)
    result = mod.check_file_exists("VERSION", "Version file")
    assert result["status"] == "pass"


def test_get_version_reads_version_file(tmp_path):
    (tmp_path / "VERSION").write_text("0.1.0-dev-preview\n")
    mod = _load_module(tmp_path)
    assert mod.get_version() == "0.1.0-dev-preview"


def test_get_version_falls_back_to_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0"\n')
    mod = _load_module(tmp_path)
    assert mod.get_version() == "0.2.0"


def test_get_version_unknown_when_nothing(tmp_path):
    mod = _load_module(tmp_path)
    assert mod.get_version() == "unknown"
