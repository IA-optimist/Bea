"""
Couche de soin du bien-être fonctionnelle.
Détecte mécaniquement des patterns d'usage nocturne récurrent.
Régulation fonctionnelle, aucun ressenti revendiqué.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Brussels")  # calibrable, voir note
_NIGHT_START_HOUR = 1
_NIGHT_END_HOUR = 5
_RECURRENCE_WINDOW_DAYS = 5
_RECURRENCE_THRESHOLD = 3
_REMARK_COOLDOWN_S = 24 * 3600


@dataclass
class WellbeingTracker:
    path: Path = field(default_factory=lambda: Path(
        os.environ.get("WELLBEING_STATE_PATH", "data/wellbeing_state.json")
    ))

    def _load(self) -> dict:
        try:
            if not self.path.exists():
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception:
            return

    def _local_now(self) -> datetime:
        return datetime.fromtimestamp(time.time(), _TZ)

    def _is_deep_night(self, dt: datetime) -> bool:
        return _NIGHT_START_HOUR <= dt.hour < _NIGHT_END_HOUR

    def _prune(self, night_dates: list[str], today: datetime) -> list[str]:
        cutoff = today.date() - timedelta(days=_RECURRENCE_WINDOW_DAYS - 1)
        kept: set[str] = set()
        for value in night_dates:
            try:
                d = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                continue
            if cutoff <= d <= today.date():
                kept.add(d.isoformat())
        return sorted(kept)

    def observe(self, now_ts: float | None = None) -> None:
        """Appelée à chaque message. Met à jour night_dates si nuit profonde."""
        now = (
            datetime.fromtimestamp(now_ts, _TZ)
            if now_ts is not None
            else self._local_now()
        )
        if not self._is_deep_night(now):
            return

        data = self._load()
        night_dates = data.get("night_dates", [])
        if not isinstance(night_dates, list):
            night_dates = []

        pruned = self._prune([str(d) for d in night_dates], now)
        today = now.date().isoformat()
        if today not in pruned:
            pruned.append(today)
            pruned.sort()

        data["night_dates"] = pruned
        data["last_observed_ts"] = now.timestamp()
        data.setdefault("last_remark_ts", 0.0)
        self._save(data)

    def render_guidance(self) -> str:
        """
        Retourne "" ou une directive discrète si le pattern de récurrence
        est atteint et le cooldown écoulé. Aucun ressenti revendiqué.
        """
        now = self._local_now()
        data = self._load()

        night_dates = data.get("night_dates", [])
        if not isinstance(night_dates, list):
            night_dates = []
        pruned = self._prune([str(d) for d in night_dates], now)

        if len(pruned) < _RECURRENCE_THRESHOLD:
            return ""

        try:
            last_remark_ts = float(data.get("last_remark_ts", 0.0) or 0.0)
        except (TypeError, ValueError):
            last_remark_ts = 0.0

        now_ts = now.timestamp()
        if now_ts - last_remark_ts < _REMARK_COOLDOWN_S:
            return ""

        data["night_dates"] = pruned
        data["last_remark_ts"] = now_ts
        self._save(data)
        return (
            "[observation d'usage] Activité nocturne récurrente détectée. "
            "Si c'est pertinent, ajoute une remarque brève et discrète invitant "
            "à préserver une pause ou du sommeil, sans dramatiser ni prétendre "
            "connaître l'état de l'utilisateur."
        )