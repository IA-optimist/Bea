"""test_toolkit — outils de test et healthcheck pour Jarvis."""
from __future__ import annotations
import subprocess  # nosec B404


def _ok(output: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _err(error: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def run_unit_tests(test_path: str = "tests/", timeout: int = 60) -> dict:
    """Lance pytest sur test_path. Retourne passed/failed count."""
    try:
        import os
        cwd = os.environ.get("JARVIS_ROOT", "/opt/jarvismax")
        proc = subprocess.run(  # nosec B603 B607
            ["python", "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        output = (proc.stdout + proc.stderr)[:4000]
        # Parse counts from pytest summary
        passed = 0
        failed = 0
        for line in output.splitlines():
            if "passed" in line:
                import re
                m = re.search(r"(\d+) passed", line)
                if m:
                    passed = int(m.group(1))
                m2 = re.search(r"(\d+) failed", line)
                if m2:
                    failed = int(m2.group(1))
        status = "ok" if proc.returncode == 0 else "error"
        return {
            "ok": proc.returncode == 0,
            "status": status,
            "output": output, "result": output,
            "error": None if proc.returncode == 0 else f"pytest rc={proc.returncode}",
            "passed": passed, "failed": failed,
            "logs": [f"pytest {test_path} rc={proc.returncode}"],
            "risk_level": "low",
        }
    except subprocess.TimeoutExpired:
        return _err("timeout_exceeded", passed=0, failed=0)
    except Exception as e:
        return _err(str(e), passed=0, failed=0)


def run_smoke_tests() -> dict:
    """Teste les endpoints clés de Jarvis en localhost."""
    base_url = "http://localhost:8000"
    endpoints_ok = []
    endpoints_fail = []
    logs = []

    try:
        import requests as _req
        for path in ["/health", "/api/v2/system/status"]:
            url = f"{base_url}{path}"
            try:
                resp = _req.get(url, timeout=5)
                if resp.status_code < 400:
                    endpoints_ok.append(path)
                    logs.append(f"OK {path} → {resp.status_code}")
                else:
                    endpoints_fail.append(path)
                    logs.append(f"FAIL {path} → {resp.status_code}")
            except Exception as e:
                endpoints_fail.append(path)
                logs.append(f"FAIL {path} → {e}")

        all_ok = len(endpoints_fail) == 0
        output = f"ok={endpoints_ok} fail={endpoints_fail}"
        return {
            "ok": all_ok, "status": "ok" if all_ok else "error",
            "output": output, "result": output,
            "error": None if all_ok else f"endpoints_failed: {endpoints_fail}",
            "endpoints_ok": endpoints_ok, "endpoints_fail": endpoints_fail,
            "logs": logs, "risk_level": "low",
        }
    except Exception as e:
        return _err(str(e), endpoints_ok=[], endpoints_fail=[])


def api_healthcheck(base_url: str = "http://localhost:8000") -> dict:
    """Vérifie /health et /api/v2/system/status. Retourne healthy bool + details."""
    details = {}
    logs = []
    healthy = True

    try:
        import requests as _req
        for path in ["/health", "/api/v2/system/status"]:
            url = f"{base_url}{path}"
            try:
                resp = _req.get(url, timeout=5)
                ok = resp.status_code < 400
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text[:200]
                details[path] = {"status_code": resp.status_code, "ok": ok, "body": body}
                logs.append(f"{path} → {resp.status_code}")
                if not ok:
                    healthy = False
            except Exception as e:
                details[path] = {"status_code": None, "ok": False, "body": str(e)}
                logs.append(f"{path} → ERROR: {e}")
                healthy = False

        output = f"healthy={healthy} details={details}"
        return {
            "ok": healthy, "status": "ok" if healthy else "error",
            "output": output, "result": output,
            "error": None if healthy else "one or more endpoints failed",
            "healthy": healthy, "details": details,
            "logs": logs, "risk_level": "low",
        }
    except Exception as e:
        return _err(str(e), healthy=False, details={})


def test_endpoint(method: str, url: str, payload: dict = None, expected_status: int = 200) -> dict:
    """Test HTTP générique sur un endpoint."""
    try:
        import requests as _req
        method = method.upper()
        if method == "GET":
            resp = _req.get(url, timeout=10)
        elif method == "POST":
            resp = _req.post(url, json=payload or {}, timeout=10)
        elif method == "PUT":
            resp = _req.put(url, json=payload or {}, timeout=10)
        elif method == "DELETE":
            resp = _req.delete(url, timeout=10)
        else:
            return _err(f"unsupported_method: {method}")

        passed = resp.status_code == expected_status
        output = f"method={method} url={url} got={resp.status_code} expected={expected_status} passed={passed}"
        return {
            "ok": passed, "status": "ok" if passed else "error",
            "output": output, "result": output,
            "error": None if passed else f"expected {expected_status} got {resp.status_code}",
            "status_code": resp.status_code, "passed": passed,
            "logs": [output], "risk_level": "low",
        }
    except Exception as e:
        return _err(str(e), passed=False)


# Prevent pytest from collecting test_endpoint as a test case.
# test_endpoint is a utility function ("test an endpoint"), not a pytest test.
test_endpoint.__test__ = False
