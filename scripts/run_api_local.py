"""Démarre la stack agent Béa complète (API 592 routes) en LOCAL, sans Docker.

Mode dégradé gracieux : Qdrant en échec-rapide (fallback mémoire locale),
Postgres/Redis absents tolérés. La cognition (CognitionOrchestrator),
MetaOrchestrator, la persistance des missions et les 57 routers fonctionnent.

Usage (venv local) :
    python scripts/run_api_local.py
    # puis :  curl -H "X-Jarvis-Token: localdev" http://127.0.0.1:8000/health

Variables (surchargeables) :
    BEA_API_PORT (def 8000), JARVIS_API_TOKEN (def "localdev").
Pour rendre ça permanent : tâche planifiée (comme Hermes_Gateway).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# .env -> os.environ (sans écraser ce qui est déjà défini)
env = ROOT / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("JARVIS_API_TOKEN", "localdev")
os.environ.setdefault("JARVIS_REQUIRE_AUTH", "true")
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")  # échec rapide -> fallback local

sys.path.insert(0, str(ROOT))


def main() -> None:
    import uvicorn
    port = int(os.environ.get("BEA_API_PORT", "8000"))
    # Bind configurable : défaut 127.0.0.1 (sûr). Mettre BEA_API_BIND=0.0.0.0 pour
    # exposer l'API sur toutes les interfaces (ex. accès mobile via Tailscale/LAN) —
    # protégé par JARVIS_API_TOKEN + l'access-enforcement middleware.
    bind = os.environ.get("BEA_API_BIND", "127.0.0.1")
    print(f"Béa API (stack complète, local dégradé) -> http://{bind}:{port}")
    print(f"Token : X-Jarvis-Token: {os.environ['JARVIS_API_TOKEN']}")
    uvicorn.run("api.main:app", host=bind, port=port, log_level="warning")


if __name__ == "__main__":
    main()
