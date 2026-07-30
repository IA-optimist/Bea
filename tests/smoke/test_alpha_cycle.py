from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.providers.runtime_health import ProviderHealth
from scripts import provider_healthcheck
from scripts import run_alpha_cycle


def _health(**overrides):
    base = {
        "status": "DEGRADED",
        "openrouter_key_present": False,
        "openrouter_usable": False,
        "ollama_reachable": True,
        "ollama_host_used": "http://127.0.0.1:11434",
        "ollama_models": ["gemma4:12b"],
        "default_provider": "ollama",
        "fallback_provider": "none",
        "hints": [],
    }
    base.update(overrides)
    return ProviderHealth(**base)


def test_select_provider_accepts_local_ollama_degraded():
    selected = run_alpha_cycle.select_provider(_health())

    assert selected == "ollama"


def test_select_provider_fails_cleanly_when_unavailable():
    with pytest.raises(run_alpha_cycle.AlphaCycleError, match="No LLM provider available"):
        run_alpha_cycle.select_provider(
            _health(
                status="UNAVAILABLE",
                ollama_reachable=False,
                ollama_models=[],
                default_provider="none",
            )
        )


def test_alpha_report_contract_requires_provider_used(tmp_path):
    report = run_alpha_cycle.build_alpha_report(
        mission_id="alpha-test",
        goal="test alpha cycle",
        provider_used="ollama",
        duration_s=1.0,
        report_path=tmp_path / "report.json",
        llm_response="Alpha response",
        orchestrator_context={},
        provider_health=_health().to_dict(),
        memory_retrieval={"has_lessons": False},
        checks={"boot_kernel": True},
    )

    run_alpha_cycle.validate_alpha_report_contract(report)


def test_alpha_report_contract_invalid_fails_clearly():
    with pytest.raises(run_alpha_cycle.AlphaCycleError, match="missing required alpha report field"):
        run_alpha_cycle.validate_alpha_report_contract({"mission_id": "only-one-field"})


def test_run_alpha_cycle_with_fakes_ingests_and_calls_bea_eval(tmp_path):
    calls: list[list[str]] = []

    async def fake_orchestrator(goal: str, mission_id: str, timeout_s: float):
        return SimpleNamespace(
            mission_id=mission_id,
            goal=goal,
            status=SimpleNamespace(value="done"),
            result="orchestrator result",
            metadata={
                "classification": {"task_type": "alpha_runtime"},
                "routed_provider": {"provider_id": "llm_primary"},
                "mission_lessons": {"has_lessons": True, "success_count": 1},
                "decision_trace": [{"phase": "route", "step": "provider_selected"}],
            },
        )

    async def fake_llm(goal: str, mission_id: str, timeout_s: float):
        return {
            "content": "Alpha runtime response from fake provider",
            "provider": "ollama",
            "model": "gemma4:12b",
        }

    def fake_retrieval(goal: str, task_type: str, top_k: int):
        return {"has_lessons": True, "success_count": 1, "failure_count": 0}

    def runner(cmd: list[str], **kwargs):
        calls.append([str(part) for part in cmd])
        if Path(cmd[1]).name == "bea_eval.py":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"summary": {"failed": 0}, "results": []}),
                stderr="",
            )
        return subprocess.run(cmd, **kwargs)

    result = run_alpha_cycle.run_alpha_cycle(
        work_dir=tmp_path,
        provider_health_fn=lambda: _health(),
        orchestrator_runner=fake_orchestrator,
        llm_invoker=fake_llm,
        memory_retriever=fake_retrieval,
        command_runner=runner,
        isolated_memory=True,
    )

    assert result["ok"] is True
    assert result["provider_used"] == "ollama"
    assert result["ingestion"]["reports_read"] == 1
    assert result["memory_types"]["eval_result"] >= 1
    assert result["memory_types"]["model_result"] >= 1
    assert result["memory_types"]["skill"] >= 1
    assert result["memory_types"]["test_map"] >= 1
    assert any(Path(call[1]).name == "bea_eval.py" and "--json" in call for call in calls)


def test_provider_healthcheck_treats_degraded_as_usable_for_local_alpha():
    assert provider_healthcheck._exit_code_for_status("READY") == 0
    assert provider_healthcheck._exit_code_for_status("DEGRADED") == 0
    assert provider_healthcheck._exit_code_for_status("UNAVAILABLE") == 1


def test_provider_healthcheck_normalizes_local_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")

    provider_healthcheck._normalize_cli_ollama_host()

    assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:11434"
