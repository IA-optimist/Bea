"""Watchdog Béa — vérifie API locale + SaaS Railway, alerte Telegram si changement.

Conçu pour être lancé par une tâche planifiée Windows toutes les 5 minutes.
N'alerte que quand le statut change (UP→DOWN ou DOWN→UP).
L'état est persisté dans scripts/.watchdog_state.json.

Usage (depuis le répertoire Béa, venv activé) :
    python scripts/watchdog.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("bea.watchdog")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    stream=sys.stderr)

# ── .env chargé en premier ────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        if _k and _k not in os.environ:
            os.environ[_k] = _v.strip().strip('"').strip("'")

# ── Configuration (après .env) ────────────────────────────────────────────────

_STATE_FILE = Path(__file__).parent / ".watchdog_state.json"

ENDPOINTS = {
    "Béa API":         os.getenv("BEA_API_URL", "http://127.0.0.1:8000") + "/health",
    "AutoContentFlow": "https://autocontentflow-app-production.up.railway.app/health",
    "CVOptimIA":       "https://cvoptimia-app-production.up.railway.app/health",
}

BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
_raw_ids   = os.getenv("TELEGRAM_ALLOWED_USERS", "")
_ids       = [u.strip() for u in _raw_ids.split(",") if u.strip()]
ALERT_CHAT = os.getenv("TELEGRAM_ALERT_CHAT_ID", _ids[0] if _ids else "")

TIMEOUT_S = 8


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bea-watchdog/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status < 400
    except Exception:
        return False


def _load_state() -> dict[str, bool]:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict[str, bool]) -> None:
    _STATE_FILE.write_text(json.dumps(state))


def _send_tg(text: str) -> None:
    if not BOT_TOKEN or not ALERT_CHAT:
        log.warning("no TG creds — alert: %s", text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": ALERT_CHAT, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("TG send failed: %s", e)


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    prev = _load_state()
    curr: dict[str, bool] = {}
    alerts: list[str] = []

    for name, url in ENDPOINTS.items():
        ok = _check(url)
        curr[name] = ok
        was = prev.get(name)
        if was is True and not ok:
            alerts.append(f"ALERTE : {name} est HORS LIGNE")
        elif was is False and ok:
            alerts.append(f"OK : {name} est de nouveau EN LIGNE")
        elif was is None and not ok:
            alerts.append(f"ALERTE : {name} HORS LIGNE (premier check)")

    _save_state(curr)

    if alerts:
        ts = time.strftime("%d/%m %H:%M")
        msg = f"[Watchdog Béa — {ts}]\n" + "\n".join(alerts)
        _send_tg(msg)
        log.warning(msg)
    else:
        log.info("%s — all OK", time.strftime("%H:%M:%S"))


if __name__ == "__main__":
    run()
