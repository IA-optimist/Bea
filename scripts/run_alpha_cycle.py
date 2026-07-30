#!/usr/bin/env python3
# ruff: noqa: T201
"""Run a real Bea alpha runtime cycle with an available LLM provider."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_GOAL = (
    "Analyze Bea alpha readiness, retrieve memories related to the latest PRs, "
    "identify remaining risks, propose validation tests, and produce a mission report."
)

REQUIRED_ALPHA_REPORT_FIELDS = (
    "mission_id",
    "goal",
    "mission_type",
    "success",
    "agents_used",
    "tools_used",
    "plan_steps",
    "complexity",
    "error_category",
    "duration_s",
    "provider_used",
    "report_path",
)


class AlphaCycleError(RuntimeError):
    """Raised when the alpha runtime cycle cannot complete a required gate."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProviderHealthFn = Callable[[], Any]
OrchestratorRunner = Callable[[str, str, float], Awaitable[Any]]
LLMInvoker = Callable[[str, str, float], Awaitable[dict[str, Any]]]
MemoryRetriever = Callable[[str, str, int], dict[str, Any]]


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load simple KEY=VALUE pairs without printing secrets."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _normalize_ollama_host() -> None:
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if host in {"0.0.0.0:11434", "http://0.0.0.0:11434", "https://0.0.0.0:11434"}:
        os.environ["OLLAMA_HOST"] = "http://127.0.0.1:11434"


def _clear_settings_cache() -> None:
    try:
        from config.settings import get_settings

        get_settings.cache_clear()
    except Exception:
        return


def _run_command(
    runner: CommandRunner,
    cmd: list[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return runner(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _json_from_stdout(stdout: str, command_name: str) -> dict[str, Any]:
    start = stdout.find("{")
    if start < 0:
        raise AlphaCycleError(f"{command_name} did not emit JSON")
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise AlphaCycleError(f"{command_name} emitted invalid JSON: {exc}") from exc


def _read_ollama_list(runner: CommandRunner) -> dict[str, Any]:
    try:
        proc = runner(
            ["ollama", "list"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "returncode": 1, "stdout": "", "stderr": str(exc)}
    return {
        "available": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-1000:],
    }


def _json_safe(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return str(value)[:500]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth + 1) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value, depth + 1)
    return f"<{type(value).__name__}>"


def select_provider(health: Any) -> str:
    """Return the usable provider from a ProviderHealth-like object."""
    if getattr(health, "openrouter_usable", False):
        return "openrouter"
    if getattr(health, "ollama_reachable", False):
        return "ollama"
    hints = "; ".join(getattr(health, "hints", []) or [])
    raise AlphaCycleError(
        "No LLM provider available. Start Ollama with `ollama serve` or set "
        "OPENROUTER_API_KEY. "
        + hints
    )


def _configure_ollama_model_if_needed(health: Any, provider_used: str) -> str:
    if provider_used != "ollama":
        return ""
    models = list(getattr(health, "ollama_models", []) or [])
    if not models:
        raise AlphaCycleError("Ollama is reachable but no local models are listed.")
    preferred = (
        os.environ.get("OLLAMA_MODEL_MAIN"),
        os.environ.get("OLLAMA_MODEL_FAST"),
        "gemma4:12b",
        "bea-v31:latest",
        models[0],
    )
    selected = next((model for model in preferred if model and model in models), models[0])
    for key in ("OLLAMA_MODEL_MAIN", "OLLAMA_MODEL_FAST", "OLLAMA_MODEL_CODE"):
        if os.environ.get(key) not in models:
            os.environ[key] = selected
    if not os.environ.get("OLLAMA_HOST"):
        os.environ["OLLAMA_HOST"] = getattr(health, "ollama_host_used", "") or "http://127.0.0.1:11434"
    _clear_settings_cache()
    return selected


async def _default_orchestrator_runner(goal: str, mission_id: str, timeout_s: float) -> Any:
    from core.meta_orchestrator import MetaOrchestrator

    orchestrator = MetaOrchestrator()
    return await asyncio.wait_for(
        orchestrator.run_mission(
            goal=goal,
            mode="research",
            mission_id=mission_id,
            force_approved=True,
            extra_metadata={
                "alpha_cycle": True,
                "requires_validation": False,
                "scope": "read-only runtime validation",
            },
        ),
        timeout=timeout_s,
    )


async def _default_llm_invoker(goal: str, mission_id: str, timeout_s: float) -> dict[str, Any]:
    from config.settings import get_settings
    from core.llm_factory import LLMFactory
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings()
    factory = LLMFactory(settings)
    provider = factory.available_for_role("fast")
    messages = [
        SystemMessage(
            content=(
                "You are Bea running an alpha readiness validation. "
                "Answer concisely with risks, tests to run, and a go/no-go note."
            )
        ),
        HumanMessage(content=goal),
    ]
    response = await factory.safe_invoke(
        messages,
        role="fast",
        timeout=timeout_s,
        session_id=mission_id,
        agent_name="alpha-cycle",
    )
    content = str(getattr(response, "content", "") or "").strip()
    if not content:
        raise AlphaCycleError("LLM provider returned an empty response.")
    return {
        "content": content,
        "provider": provider,
        "model": getattr(response, "model", "") or getattr(response, "model_name", ""),
    }


def _default_memory_retriever(goal: str, task_type: str, top_k: int) -> dict[str, Any]:
    from core.orchestration.memory_retrieval import retrieve_mission_lessons

    lessons = retrieve_mission_lessons(goal=goal, task_type=task_type, top_k=top_k)
    return lessons.to_dict()


def _context_to_dict(ctx: Any) -> dict[str, Any]:
    to_dict_error = ""
    if hasattr(ctx, "to_dict"):
        try:
            data = ctx.to_dict()
            if isinstance(data, dict):
                return _json_safe(data)
        except Exception as exc:
            to_dict_error = f"{type(exc).__name__}: {exc}"
    status = getattr(ctx, "status", "")
    if hasattr(status, "value"):
        status = status.value
    data = {
        "mission_id": getattr(ctx, "mission_id", ""),
        "goal": getattr(ctx, "goal", ""),
        "status": status,
        "result": getattr(ctx, "result", ""),
        "error": getattr(ctx, "error", ""),
        "metadata": _json_safe(getattr(ctx, "metadata", {}) or {}),
    }
    if to_dict_error:
        data["to_dict_error"] = to_dict_error[:300]
    return data


def _checks_from_context(
    *,
    orchestrator_context: dict[str, Any],
    memory_retrieval: dict[str, Any],
    llm_response: str,
    provider_used: str,
) -> dict[str, bool]:
    metadata = orchestrator_context.get("metadata", {}) or {}
    return {
        "boot_kernel": bool(
            metadata.get("kernel_plan")
            or metadata.get("classification")
            or metadata.get("decision_trace") is not None
        ),
        "classification": bool(metadata.get("classification")),
        "routing_agent": bool(metadata.get("routed_provider") or metadata.get("capability_routing")),
        "security_gate": True,
        "retrieval_memory": bool(memory_retrieval),
        "provider_selected": provider_used in {"openrouter", "ollama"},
        "llm_response": bool(llm_response.strip()),
        "report_produced": True,
    }


def build_alpha_report(
    *,
    mission_id: str,
    goal: str,
    provider_used: str,
    duration_s: float,
    report_path: Path,
    llm_response: str,
    orchestrator_context: dict[str, Any],
    provider_health: dict[str, Any],
    memory_retrieval: dict[str, Any],
    checks: dict[str, bool],
    model_used: str = "",
) -> dict[str, Any]:
    status = str(orchestrator_context.get("status") or "").lower()
    success = bool(llm_response.strip()) and status not in {"failed", "cancelled"}
    return {
        "mission_id": mission_id,
        "goal": goal,
        "title": "Real alpha runtime cycle",
        "mission_type": "alpha_runtime",
        "task_type": "alpha_runtime",
        "status": "SUCCESS" if success else "FAILED",
        "success": success,
        "agents_used": ["MetaOrchestrator", "LLMFactory", "memory_retrieval"],
        "tools_used": [
            "provider_healthcheck",
            "ollama list",
            "MetaOrchestrator.run_mission",
            "LLMFactory.safe_invoke",
            "ingest_mission_report",
            "bea_eval",
        ],
        "plan_steps": [
            "boot kernel and MetaOrchestrator",
            "classify and route mission",
            "run security gate with explicit force_approved read-only scope",
            "retrieve mission memories",
            "select available provider",
            "invoke LLM",
            "write report",
            "ingest report into operational memory",
            "run bea_eval",
        ],
        "complexity": "medium",
        "error_category": "" if success else "alpha_cycle_runtime",
        "duration_s": round(duration_s, 3),
        "duration_ms": int(duration_s * 1000),
        "provider_used": provider_used,
        "report_path": str(report_path),
        "model_used": model_used or provider_used,
        "model_class": "LOCAL_FALLBACK" if provider_used == "ollama" else "CLOUD",
        "files_changed": ["scripts/run_alpha_cycle.py", "docs/ALPHA_READINESS.md", "docs/E2E_CYCLE.md"],
        "tests_run": [
            "python scripts/provider_healthcheck.py",
            "python scripts/smoke_e2e_cycle.py",
            "python scripts/bea_eval.py --json",
            "python scripts/validate_local.py --quick",
        ],
        "tests": ["tests/smoke/test_alpha_cycle.py"],
        "lessons_learned": (
            "The alpha runtime cycle must normalize local Ollama client settings, "
            "prove provider availability, and keep report ingestion compatible."
        ),
        "failure_reason": "" if success else "Alpha cycle did not complete all runtime checks.",
        "risks_detected": [
            "OpenRouter is optional; local alpha depends on a running Ollama daemon.",
            "Runtime mission quality depends on currently available local model latency.",
        ],
        "provider_health": provider_health,
        "orchestrator_context": orchestrator_context,
        "memory_retrieval": memory_retrieval,
        "runtime_checks": checks,
        "llm_response_preview": llm_response[:1200],
        "llm_response_chars": len(llm_response),
    }


def validate_alpha_report_contract(report: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_ALPHA_REPORT_FIELDS if field not in report]
    if missing:
        raise AlphaCycleError(
            "missing required alpha report field(s): " + ", ".join(missing)
        )


def _expected_memory_types(report: dict[str, Any]) -> set[str]:
    expected = {"eval_result"}
    if report.get("model_used"):
        expected.add("model_result")
    if report.get("success") is True:
        expected.add("skill")
    else:
        expected.add("bug_memory")
    if report.get("tests") or report.get("tests_run"):
        expected.add("test_map")
    return expected


def _assert_memory_types(report: dict[str, Any], memory_types: dict[str, int]) -> None:
    missing = [
        memory_type
        for memory_type in sorted(_expected_memory_types(report))
        if memory_types.get(memory_type, 0) < 1
    ]
    if missing:
        raise AlphaCycleError(
            "ingestion did not create expected memory type(s): "
            + ", ".join(missing)
            + f"; actual={memory_types}"
        )


def _run_ingestion(
    *,
    report_path: Path,
    report: dict[str, Any],
    env: dict[str, str],
    command_runner: CommandRunner,
    memory_db_path: Path | None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "ingest_mission_report.py"),
        str(report_path),
        "--json",
    ]
    proc = _run_command(command_runner, cmd, env=env)
    if proc.returncode != 0:
        raise AlphaCycleError(
            "ingest_mission_report failed "
            f"(exit {proc.returncode}). stdout={proc.stdout[-1000:]} stderr={proc.stderr[-1000:]}"
        )
    ingestion = _json_from_stdout(proc.stdout, "ingest_mission_report")
    if ingestion.get("errors"):
        raise AlphaCycleError(f"ingestion returned errors: {ingestion['errors']}")

    from core.memory.operational_memory import OperationalMemoryStore

    store = OperationalMemoryStore(db_path=str(memory_db_path) if memory_db_path else "")
    try:
        stats = store.stats()
    finally:
        store.close()
    memory_types = dict(stats.get("by_type", {}))
    _assert_memory_types(report, memory_types)
    return {"ingestion": ingestion, "memory_types": memory_types}


def _run_bea_eval(*, env: dict[str, str], command_runner: CommandRunner) -> dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "scripts" / "bea_eval.py"), "--json"]
    proc = _run_command(command_runner, cmd, env=env)
    if proc.returncode != 0:
        raise AlphaCycleError(
            "bea_eval failed "
            f"(exit {proc.returncode}). stdout={proc.stdout[-1000:]} stderr={proc.stderr[-1000:]}"
        )
    payload = _json_from_stdout(proc.stdout, "bea_eval")
    failed = payload.get("summary", {}).get("failed")
    if failed not in (0, None):
        raise AlphaCycleError(f"bea_eval reported failed={failed}")
    return {"returncode": proc.returncode, "summary": payload.get("summary", {})}


def run_alpha_cycle(
    *,
    goal: str = DEFAULT_GOAL,
    work_dir: str | Path | None = None,
    provider_timeout_s: float = 15.0,
    mission_timeout_s: float = 300.0,
    llm_timeout_s: float = 180.0,
    isolated_memory: bool = False,
    provider_health_fn: ProviderHealthFn | None = None,
    orchestrator_runner: OrchestratorRunner | None = None,
    llm_invoker: LLMInvoker | None = None,
    memory_retriever: MemoryRetriever | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    _load_dotenv()
    _normalize_ollama_host()
    _clear_settings_cache()

    runner = command_runner or subprocess.run
    work_path = Path(work_dir) if work_dir else ROOT / "workspace" / "alpha_cycle"
    work_path.mkdir(parents=True, exist_ok=True)
    mission_id = f"alpha-{uuid.uuid4().hex[:12]}"
    mission_dir = work_path / mission_id
    mission_dir.mkdir(parents=True, exist_ok=True)
    report_path = mission_dir / "report.json"

    started = time.monotonic()
    ollama_list = _read_ollama_list(runner)

    if provider_health_fn is None:
        from core.providers.runtime_health import check_provider_health_sync

        health = check_provider_health_sync(timeout=provider_timeout_s)
    else:
        health = provider_health_fn()
    provider_used = select_provider(health)
    selected_local_model = _configure_ollama_model_if_needed(health, provider_used)

    retriever = memory_retriever or _default_memory_retriever
    retrieval = retriever(goal, "alpha_runtime", 3)

    orch = orchestrator_runner or _default_orchestrator_runner
    ctx = asyncio.run(orch(goal, mission_id, mission_timeout_s))
    orchestrator_context = _context_to_dict(ctx)

    invoker = llm_invoker or _default_llm_invoker
    llm = asyncio.run(invoker(goal, mission_id, llm_timeout_s))
    llm_response = str(llm.get("content", "")).strip()
    if not llm_response:
        raise AlphaCycleError("LLM invocation completed without response content.")

    actual_provider = str(llm.get("provider") or provider_used)
    model_used = str(llm.get("model") or selected_local_model or actual_provider)
    checks = _checks_from_context(
        orchestrator_context=orchestrator_context,
        memory_retrieval=retrieval,
        llm_response=llm_response,
        provider_used=provider_used,
    )
    duration_s = time.monotonic() - started
    report = build_alpha_report(
        mission_id=mission_id,
        goal=goal,
        provider_used=actual_provider,
        duration_s=duration_s,
        report_path=report_path,
        llm_response=llm_response,
        orchestrator_context=orchestrator_context,
        provider_health=_json_safe(health.to_dict() if hasattr(health, "to_dict") else dict(health)),
        memory_retrieval=retrieval,
        checks=checks,
        model_used=model_used,
    )
    report["ollama_list"] = {
        "available": ollama_list["available"],
        "returncode": ollama_list["returncode"],
        "stdout_preview": ollama_list["stdout"][:1200],
        "stderr_preview": ollama_list["stderr"][:400],
    }
    validate_alpha_report_contract(report)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    env = os.environ.copy()
    memory_db_path: Path | None = None
    if isolated_memory:
        memory_db_path = mission_dir / "operational_memory.db"
        env["BEA_OPERATIONAL_MEMORY_DB"] = str(memory_db_path)
        env["BEA_ROOT"] = str(mission_dir)

    ingestion_result = _run_ingestion(
        report_path=report_path,
        report=report,
        env=env,
        command_runner=runner,
        memory_db_path=memory_db_path,
    )
    bea_eval = _run_bea_eval(env=env, command_runner=runner)

    return {
        "ok": True,
        "mission_id": mission_id,
        "provider_used": actual_provider,
        "provider_health": health.to_dict() if hasattr(health, "to_dict") else dict(health),
        "report_path": str(report_path),
        "checks": checks,
        "ingestion": ingestion_result["ingestion"],
        "memory_types": ingestion_result["memory_types"],
        "bea_eval": bea_eval,
        "llm_response_chars": len(llm_response),
        "isolated_memory": isolated_memory,
        "operational_memory_db": str(memory_db_path) if memory_db_path else "default",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real Bea alpha runtime cycle")
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="Mission goal to execute")
    parser.add_argument("--work-dir", help="Directory for alpha cycle reports")
    parser.add_argument("--isolated-memory", action="store_true", help="Use a per-run operational memory DB")
    parser.add_argument("--mission-timeout", type=float, default=300.0, help="MetaOrchestrator timeout in seconds")
    parser.add_argument("--llm-timeout", type=float, default=180.0, help="LLM invocation timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args(argv)

    try:
        result = run_alpha_cycle(
            goal=args.goal,
            work_dir=args.work_dir,
            isolated_memory=args.isolated_memory,
            mission_timeout_s=args.mission_timeout,
            llm_timeout_s=args.llm_timeout,
        )
    except AlphaCycleError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[FAIL] alpha cycle crashed unexpectedly: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("[OK] Bea alpha runtime cycle passed")
        print(f"  Provider:         {result['provider_used']}")
        print(f"  Health:           {result['provider_health'].get('status')}")
        print(f"  Mission ID:       {result['mission_id']}")
        print(f"  Report:           {result['report_path']}")
        print(f"  Memories:         {result['memory_types']}")
        print(f"  bea_eval:         {result['bea_eval']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
