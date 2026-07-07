from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class _Settings:
    self_improve_enabled: bool = False
    bea_skip_improvement_gate: bool = False
    bea_session_store: str = "memory"
    bea_redis_url: str = ""


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_aggregate_levels_fold_fail_closed():
    from scripts.bea_doctor import aggregate_tier_status, DoctorCheckResult

    checks = {
        "ok": DoctorCheckResult("ok", "PASS"),
        "warn": DoctorCheckResult("warn", "WARN"),
        "fail": DoctorCheckResult("fail", "FAIL"),
    }
    assert aggregate_tier_status(checks, ("ok",)) == "PASS"
    assert aggregate_tier_status(checks, ("ok", "warn")) == "WARN"
    assert aggregate_tier_status(checks, ("fail",)) == "FAIL"


def test_public_beta_flag_false_is_coherent(tmp_path: Path):
    from scripts.bea_doctor import check_public_beta_flag

    _write(
        tmp_path,
        "PUBLIC_BETA_CHECKLIST.md",
        "READY_FOR_PUBLIC_BETA: false\n",
    )
    _write(
        tmp_path,
        "README_PUBLIC_BETA.md",
        "Béa is currently a private beta / developer preview / experimental system.\n",
    )
    result = check_public_beta_flag(tmp_path)
    assert result.status == "PASS"


def test_docs_contradiction_is_detected(tmp_path: Path):
    from scripts.bea_doctor import check_docs_status_truth

    _write(tmp_path, "README.md", "Béa is public beta ready.\n")
    _write(tmp_path, "README_PUBLIC_BETA.md", "Status: private beta / experimental.\n")
    _write(tmp_path, "PUBLIC_BETA_CHECKLIST.md", "READY_FOR_PUBLIC_BETA: false\n")
    _write(tmp_path, "docs/STATUS.md", "Ready for public beta: yes.\n")

    result = check_docs_status_truth(tmp_path)
    assert result.status == "FAIL"


def test_docs_ignore_unrelated_production_ready_phrase(tmp_path: Path):
    from scripts.bea_doctor import check_docs_status_truth, check_public_beta_flag

    _write(tmp_path, "README.md", "Béa is private beta / experimental.\n")
    _write(tmp_path, "README_PUBLIC_BETA.md", "Status: private beta / experimental.\n")
    _write(tmp_path, "PUBLIC_BETA_CHECKLIST.md", "READY_FOR_PUBLIC_BETA: false\n")
    _write(tmp_path, "docs/STATUS.md", "Production-ready infrastructure, registry currently empty.\n")

    assert check_public_beta_flag(tmp_path).status == "PASS"
    assert check_docs_status_truth(tmp_path).status == "PASS"


def test_secret_hygiene_fails_on_probable_secret(tmp_path: Path):
    from scripts.bea_doctor import check_secret_hygiene

    _write(
        tmp_path,
        "config/example.py",
        'OPENAI_API_KEY = "sk-abc1234567890abcdef1234567890"\n',
    )
    result = check_secret_hygiene(tmp_path)
    assert result.status == "FAIL"


def test_secret_hygiene_ignores_scrubber_fixtures(tmp_path: Path):
    from scripts.bea_doctor import check_secret_hygiene

    _write(
        tmp_path,
        "tests/test_secret_scrubbing.py",
        """
        def test_scrub_secrets():
            text = "api_key=sk-abcdef1234567890abcdef1234567890"
            assert "sk-abcdef" not in text
            assert "redact" in "scrub and redact fixtures"
        """,
    )
    result = check_secret_hygiene(tmp_path)
    assert result.status == "PASS"


def test_self_improvement_default_off_fail_when_enabled(tmp_path: Path):
    from scripts.bea_doctor import check_self_improvement_default_off

    result = check_self_improvement_default_off(tmp_path, _Settings(True, False))
    assert result.status == "FAIL"


def test_session_store_unknown_never_passes(tmp_path: Path):
    from scripts.bea_doctor import check_session_store_safety

    result = check_session_store_safety(tmp_path)
    assert result.status in {"WARN", "FAIL"}


def test_missing_session_store_blocks_public_beta(tmp_path: Path):
    from scripts.bea_doctor import run_doctor

    _write(tmp_path, "README.md", "Béa repo\n")
    _write(tmp_path, "README_PUBLIC_BETA.md", "Status: private beta / experimental.\n")
    _write(tmp_path, "PUBLIC_BETA_CHECKLIST.md", "READY_FOR_PUBLIC_BETA: false\n")
    _write(tmp_path, "docs/STATUS.md", "Private beta only.\n")
    _write(tmp_path, "scripts/private_beta_gate.py", "print('ok')\n")
    _write(tmp_path, "scripts/audit_memory_store.py", "print('ok')\n")
    _write(tmp_path, "scripts/verify_boot.sh", "echo ok\n")
    _write(tmp_path, "scripts/verify_prod.sh", "echo ok\n")
    _write(tmp_path, "scripts/verify-e2e.sh", "echo ok\n")
    _write(tmp_path, "validate_p0p1.sh", "echo ok\n")
    _write(tmp_path, "core/orchestrator_v2.py", "# stub\n")
    _write(tmp_path, "core/self_critic.py", "# stub\n")
    _write(tmp_path, "tests/core/test_critic_rerun_forcing.py", "def test_x(): pass\n")
    _write(tmp_path, "tests/core/test_critic_pass_forcing_runtime.py", "def test_x(): pass\n")
    _write(tmp_path, "tests/core/test_critic_rerun_log_context.py", "def test_x(): pass\n")

    report = run_doctor(repo_root=tmp_path, settings=_Settings())
    assert report.checks["session_store_safety"].status == "FAIL"
    assert report.public_beta_status == "FAIL"


def test_session_store_redis_configured_is_not_fail(tmp_path: Path):
    from scripts.bea_doctor import check_session_store_safety

    result = check_session_store_safety(
        tmp_path,
    )
    assert result.status == "FAIL"

    from scripts.bea_doctor import run_doctor

    report = run_doctor(
        repo_root=tmp_path,
        settings=_Settings(bea_session_store="redis", bea_redis_url="redis://localhost:6379/0"),
    )
    assert report.checks["session_store_safety"].status in {"WARN", "PASS"}


def test_dangerous_tools_without_gate_fail(tmp_path: Path):
    from scripts.bea_doctor import check_dangerous_tools_gated

    _write(
        tmp_path,
        "core/tool_executor.py",
        "def run_shell_command(cmd):\n    return cmd\n",
    )
    result = check_dangerous_tools_gated(tmp_path)
    assert result.status == "FAIL"


def test_doctor_report_text_and_json_shape(tmp_path: Path):
    from scripts.bea_doctor import run_doctor

    _write(tmp_path, "README.md", "Béa repo\n")
    _write(tmp_path, "README_PUBLIC_BETA.md", "Status: private beta / experimental.\n")
    _write(tmp_path, "PUBLIC_BETA_CHECKLIST.md", "READY_FOR_PUBLIC_BETA: false\n")
    _write(tmp_path, "docs/STATUS.md", "Private beta only.\n")
    report = run_doctor(repo_root=tmp_path, settings=_Settings())

    payload = report.to_dict()
    assert "local_dev" in payload
    assert "private_beta" in payload
    assert "public_beta" in payload
    assert "checks" in payload
    assert "recommendation" in payload
    assert "session_store_safety" in payload["checks"]
    assert payload["checks"]["session_store_safety"]["status"] in {"PASS", "WARN", "FAIL"}

    text = report.to_text()
    assert "Local dev" in text
    assert "Private beta" in text
    assert "Public beta" in text


def test_public_beta_false_prevents_public_pass(tmp_path: Path):
    from scripts.bea_doctor import run_doctor

    _write(tmp_path, "README.md", "Béa is experimental.\n")
    _write(tmp_path, "README_PUBLIC_BETA.md", "Status: private beta / experimental.\n")
    _write(tmp_path, "PUBLIC_BETA_CHECKLIST.md", "READY_FOR_PUBLIC_BETA: false\n")
    _write(tmp_path, "docs/STATUS.md", "Private beta only.\n")
    report = run_doctor(repo_root=tmp_path, settings=_Settings())
    assert report.public_beta_status == "FAIL"
