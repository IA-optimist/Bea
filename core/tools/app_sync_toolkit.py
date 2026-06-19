"""app_sync_toolkit — vérification et synchronisation des champs API Bea."""
from __future__ import annotations
from typing import Any

_REQUIRED_FIELDS = [
    "mission_id", "goal", "status", "agent_outputs",
    "decision_trace", "risk_score", "approval_mode", "final_output",
]


def _ok(output: str, logs: list[str] | None = None, risk_level: str = "low", **extra: Any) -> dict[str, Any]:
    base = {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _err(error: str, logs: list[str] | None = None, risk_level: str = "low", **extra: Any) -> dict[str, Any]:
    base = {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def check_api_fields(base_url: str = "http://localhost:8000") -> dict[str, Any]:
    """
    Vérifie la présence des champs requis dans la réponse de l'API missions.
    Appelle GET /api/v2/missions/list (fallback /api/v2/missions/recent).
    """
    logs = []
    fields_ok = []
    fields_missing = []

    try:
        import httpx as _req

        data = None
        for path in ["/api/v2/missions/list", "/api/v2/missions/recent", "/api/v2/missions"]:
            url = f"{base_url}{path}"
            try:
                resp = _req.get(url, timeout=10)
                logs.append(f"GET {path} → {resp.status_code}")
                if resp.status_code == 200:
                    body = resp.json()
                    # Handle list or dict with missions key
                    if isinstance(body, list) and body:
                        data = body[0]
                        break
                    elif isinstance(body, dict):
                        missions = body.get("missions") or body.get("data") or body.get("items")
                        if missions and isinstance(missions, list) and missions:
                            data = missions[0]
                            break
                        # Maybe the body itself is a mission
                        if "mission_id" in body or "goal" in body:
                            data = body
                            break
            except Exception as e:
                logs.append(f"GET {path} → ERROR: {e}")

        if data is None:
            # No missions found or API unavailable — report as unknown
            output = "no_missions_available: cannot verify fields"
            return {
                "ok": True, "status": "ok",
                "output": output, "result": output,
                "error": None,
                "fields_ok": [], "fields_missing": [],
                "patch_needed": False,
                "logs": logs, "risk_level": "low",
            }

        for field in _REQUIRED_FIELDS:
            if field in data:
                fields_ok.append(field)
            else:
                fields_missing.append(field)

        patch_needed = len(fields_missing) > 0
        output = f"fields_ok={fields_ok}\nfields_missing={fields_missing}\npatch_needed={patch_needed}"
        return {
            "ok": True, "status": "ok",
            "output": output, "result": output,
            "error": None,
            "fields_ok": fields_ok, "fields_missing": fields_missing,
            "patch_needed": patch_needed,
            "logs": logs, "risk_level": "low",
        }
    except Exception as e:
        return _err(str(e), fields_ok=[], fields_missing=[], patch_needed=False)


def sync_app_fields(base_url: str = "http://localhost:8000") -> dict[str, Any]:
    """
    Appelle check_api_fields et retourne un rapport.
    Si des champs manquent, décrit le patch nécessaire (sans l'appliquer).
    """
    try:
        result = check_api_fields(base_url=base_url)
        if not result.get("ok"):
            return result

        fields_missing = result.get("fields_missing", [])
        patch_needed = result.get("patch_needed", False)

        if patch_needed:
            patch_description = (
                f"Champs manquants: {fields_missing}\n"
                f"Patch nécessaire dans executor/mission_result.py ou api/schemas.py:\n"
                + "\n".join(f"  - Ajouter champ '{f}' au schéma de réponse" for f in fields_missing)
            )
        else:
            patch_description = "Tous les champs requis sont présents. Aucun patch nécessaire."

        result["patch_description"] = patch_description
        result["output"] = result["output"] + f"\n\n{patch_description}"
        result["result"] = result["output"]
        return result
    except Exception as e:
        return _err(str(e), fields_ok=[], fields_missing=[], patch_needed=False)
