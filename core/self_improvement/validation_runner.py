"""
BEA MAX — Self-Improvement Controller V1
Module D : ValidationRunner

Lance une suite de tests HTTP réels contre le VPS Bea.
Timeout : 30s par test, retry 0 (fail fast).
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class TestResult:
    test_name:   str
    passed:      bool
    details:     str
    duration_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    report_id:   str
    timestamp:   str
    verdict:     str           # "PASS" | "PARTIAL" | "FAIL"
    tests:       list[TestResult]  = field(default_factory=list)
    ram_metrics: dict              = field(default_factory=dict)
    summary:     str               = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class ValidationRunner:
    """
    Exécute une suite de tests HTTP contre l'API BeaMax.
    Timeout par test : 30s. Pas de retry.
    """

    _TIMEOUT_S = 30
    _last_report: ValidationReport | None = None

    def run_validation_suite(self, vps_base_url: str) -> ValidationReport:
        """
        Lance tous les tests et retourne un ValidationReport.
        Stocke le dernier rapport en mémoire de classe.
        """
        base = vps_base_url.rstrip("/")
        results: list[TestResult] = []

        results.append(self._test_health(base))
        results.append(self._test_mission_simple(base))
        results.append(self._test_capability_query(base))
        results.append(self._test_api_missions_list(base))
        results.append(self._test_ram_bounds(base))

        passed  = sum(1 for r in results if r.passed)
        total   = len(results)
        verdict = "PASS" if passed == total else ("PARTIAL" if passed > 0 else "FAIL")

        ram_metrics = self._collect_ram_metrics()

        summary = (
            f"{passed}/{total} tests passés — verdict={verdict}. "
            + (f"RAM: {ram_metrics}" if ram_metrics else "")
        )

        report = ValidationReport(
            report_id=str(uuid.uuid4())[:8],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            verdict=verdict,
            tests=results,
            ram_metrics=ram_metrics,
            summary=summary,
        )

        ValidationRunner._last_report = report
        return report

    @classmethod
    def get_last_report(cls) -> ValidationReport | None:
        return cls._last_report

    # ── Tests ─────────────────────────────────────────────────────────────────

    def _test_health(self, base: str) -> TestResult:
        return self._http_get(
            name="test_health",
            url=f"{base}/health",
            check=lambda d: d.get("status") == "ok",
            expect_desc="GET /health → 200, status=ok",
        )

    def _test_mission_simple(self, base: str) -> TestResult:
        payload = json.dumps({"input": "c'est quoi un LLM", "mode": "auto"}).encode()
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{base}/api/v2/task",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._TIMEOUT_S) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                body = json.loads(resp.read().decode())
            ms = int((time.monotonic() - t0) * 1000)

            mission_id = (body.get("data") or {}).get("mission_id")
            if not mission_id:
                return TestResult("test_mission_simple", False, "Pas de mission_id dans la réponse", ms)

            # Attendre la complétion (polling simple, max 60s)
            final_output = self._wait_for_completion(base, mission_id, max_wait_s=60)
            ms = int((time.monotonic() - t0) * 1000)

            if final_output:
                return TestResult("test_mission_simple", True, f"final_output ok ({len(final_output)} chars)", ms)
            return TestResult("test_mission_simple", False, "final_output vide après complétion", ms)

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            return TestResult("test_mission_simple", False, f"Exception: {str(e)[:100]}", ms)

    def _test_capability_query(self, base: str) -> TestResult:
        payload = json.dumps({"input": "explique ce que tu sais faire", "mode": "auto"}).encode()
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(
                f"{base}/api/v2/task",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._TIMEOUT_S) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                body = json.loads(resp.read().decode())
            ms = int((time.monotonic() - t0) * 1000)

            mission_id = (body.get("data") or {}).get("mission_id")
            if not mission_id:
                return TestResult("test_capability_query", False, "Pas de mission_id", ms)

            # Lire le détail de la mission
            time.sleep(2)
            mission_data = self._get_mission(base, mission_id)
            ms = int((time.monotonic() - t0) * 1000)

            agents = (mission_data.get("data") or {}).get("agents_selected", [])
            final  = (mission_data.get("data") or {}).get("final_output", "")

            if final and len(agents) == 0:
                return TestResult("test_capability_query", True, "agents_selected=[], final_output ok", ms)
            elif final:
                return TestResult("test_capability_query", True, f"final_output ok (agents={len(agents)})", ms)
            return TestResult("test_capability_query", False, f"final_output vide, agents={agents}", ms)

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            return TestResult("test_capability_query", False, f"Exception: {str(e)[:100]}", ms)

    def _test_api_missions_list(self, base: str) -> TestResult:
        return self._http_get(
            name="test_api_missions_list",
            url=f"{base}/api/v2/missions",
            check=lambda d: "data" in d and "missions" in (d.get("data") or {}),
            expect_desc="GET /api/v2/missions → 200, liste valide",
        )

    def _test_ram_bounds(self, base: str) -> TestResult:
        t0 = time.monotonic()
        try:
            from api.mission_store import MissionStateStore
            store = MissionStateStore.get()
            total_events = sum(len(v) for v in store._logs.values())
            ms = int((time.monotonic() - t0) * 1000)
            if total_events < 500:
                return TestResult("test_ram_bounds", True, f"events_in_store={total_events} < 500", ms)
            return TestResult("test_ram_bounds", False, f"events_in_store={total_events} ≥ 500 — seuil dépassé", ms)
        except Exception:
            # Fallback : tenter via API
            return self._http_get(
                name="test_ram_bounds",
                url=f"{base}/api/v2/status",
                check=lambda d: d.get("ok") is True,
                expect_desc="GET /api/v2/status → 200 (ram check fallback)",
            )

    # ── Helpers HTTP ──────────────────────────────────────────────────────────

    def _http_get(self, name: str, url: str, check, expect_desc: str) -> TestResult:
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=self._TIMEOUT_S) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                body = json.loads(resp.read().decode())
            ms = int((time.monotonic() - t0) * 1000)
            if check(body):
                return TestResult(name, True, expect_desc, ms)
            return TestResult(name, False, f"Check échoué — body={str(body)[:100]}", ms)
        except urllib.error.HTTPError as e:
            ms = int((time.monotonic() - t0) * 1000)
            return TestResult(name, False, f"HTTP {e.code}: {str(e)[:80]}", ms)
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            return TestResult(name, False, f"Exception: {str(e)[:100]}", ms)

    def _wait_for_completion(self, base: str, mission_id: str, max_wait_s: int = 25) -> str:
        """Poll /api/v2/missions/{id} jusqu'à DONE ou timeout."""
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline:
            try:
                data = self._get_mission(base, mission_id)
                mission = data.get("data") or {}
                status  = mission.get("status", "")
                final   = mission.get("final_output", "")
                if status in ("DONE", "MissionStatus.DONE") and final:
                    return final
                if status in ("REJECTED", "BLOCKED"):
                    return ""
            except Exception as _exc:
                log.warning("swallowed_exception", action="validation_runner_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            time.sleep(2)
        return ""

    def _get_mission(self, base: str, mission_id: str) -> dict:
        with urllib.request.urlopen(  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            f"{base}/api/v2/missions/{mission_id}", timeout=10
        ) as resp:
            return json.loads(resp.read().decode())

    def _collect_ram_metrics(self) -> dict:
        metrics: dict = {}
        try:
            from api.mission_store import MissionStateStore
            store = MissionStateStore.get()
            metrics["events_in_store"] = sum(len(v) for v in store._logs.values())
        except Exception as _exc:
            log.warning("swallowed_exception", action="validation_runner_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        try:
            from core.self_improvement.improvement_planner import ImprovementPlanner
            proposals = ImprovementPlanner().load_proposals()
            metrics["proposals_count"] = len(proposals)
        except Exception as _exc:
            log.warning("swallowed_exception", action="validation_runner_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        try:
            from core.self_improvement.failure_collector import _FAILURE_LOG
            if _FAILURE_LOG.exists():
                lines = _FAILURE_LOG.read_text("utf-8").strip().splitlines()
                metrics["failure_log_lines"] = len(lines)
            else:
                metrics["failure_log_lines"] = 0
        except Exception as _exc:
            log.warning("swallowed_exception", action="validation_runner_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return metrics
