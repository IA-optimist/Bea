"""
BEA MAX — Mode System v1
Contrôle du niveau d'autonomie de Bea.

3 modes :

  MANUAL     → Bea ne fait rien sans validation explicite.
               Chaque action, même LOW risk, attend approbation.

  SUPERVISED → Mode par défaut.
               LOW risk  → approbation automatique.
               MEDIUM    → approbation automatique si score shadow ≥ 7.0.
               HIGH      → validation requise.
               CRITICAL  → validation requise + avertissement fort.

  AUTO       → Bea agit seul.
               LOW / MEDIUM / HIGH → auto.
               CRITICAL → validation requise (toujours).

Persistance : workspace/system_mode.json
"""
from __future__ import annotations

import json
import time
from enum import Enum
from pathlib import Path
import structlog

log = structlog.get_logger()

_STORAGE = Path("workspace/system_mode.json")


# ── Mode ──────────────────────────────────────────────────────────────────────

class SystemMode(str, Enum):
    MANUAL     = "MANUAL"
    SUPERVISED = "SUPERVISED"
    AUTO       = "AUTO"


# ── Règles par mode et risque ─────────────────────────────────────────────────

# (mode, risk) → True = auto-approve, False = require human
_AUTO_APPROVE_RULES: dict[tuple[str, str], bool] = {
    # MANUAL : jamais d'auto
    ("MANUAL", "LOW"):      False,
    ("MANUAL", "MEDIUM"):   False,
    ("MANUAL", "HIGH"):     False,
    ("MANUAL", "CRITICAL"): False,

    # SUPERVISED : LOW auto, le reste demande validation
    ("SUPERVISED", "LOW"):      True,
    ("SUPERVISED", "MEDIUM"):   False,   # auto si shadow_score >= 7.0
    ("SUPERVISED", "HIGH"):     False,
    ("SUPERVISED", "CRITICAL"): False,

    # AUTO : tout sauf CRITICAL
    ("AUTO", "LOW"):      True,
    ("AUTO", "MEDIUM"):   True,
    ("AUTO", "HIGH"):     True,
    ("AUTO", "CRITICAL"): False,   # toujours validation
}

# Score shadow minimum pour auto-approuver MEDIUM en SUPERVISED
_SUPERVISED_MEDIUM_MIN_SCORE = 7.0


# ── Mode System ───────────────────────────────────────────────────────────────

class ModeSystem:
    """
    Gestionnaire du mode d'autonomie.

    Usage :
        ms = ModeSystem()
        ms.set_mode("SUPERVISED")
        auto = ms.should_auto_approve("LOW")           # True
        auto = ms.should_auto_approve("MEDIUM", 7.5)   # True (score OK)
        auto = ms.should_auto_approve("HIGH")          # False → demande humaine
    """

    def __init__(self, storage: Path|str = _STORAGE):
        self._path = Path(storage)
        self._mode = SystemMode.SUPERVISED   # défaut
        self._changed_at = time.time()
        self._changed_by = "system"
        self._load()

    # ── API publique ──────────────────────────────────────────────────────────

    def get_mode(self) -> SystemMode:
        return self._mode

    def set_mode(self, mode: str, changed_by: str = "user") -> SystemMode:
        """Change le mode. Accepte 'MANUAL', 'SUPERVISED', 'AUTO'."""
        mode_upper = str(mode).upper().strip()
        try:
            self._mode       = SystemMode(mode_upper)
            self._changed_at = time.time()
            self._changed_by = changed_by
            self._save()
            log.info("mode_changed", mode=self._mode, by=changed_by)
            return self._mode
        except ValueError:
            valid = [m.value for m in SystemMode]
            raise ValueError(f"Mode invalide : {mode!r}. Valeurs valides : {valid}")

    def should_auto_approve(
        self,
        risk:         str,
        shadow_score: float = 0.0,
    ) -> bool:
        """
        Retourne True si l'action peut être approuvée automatiquement.

        Paramètres :
            risk         : "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
            shadow_score : score shadow advisor (0.0 → 10.0), utilisé en SUPERVISED
        """
        risk_upper = str(risk).upper().strip()
        mode_val   = self._mode.value

        base = _AUTO_APPROVE_RULES.get((mode_val, risk_upper), False)

        # Cas spécial : SUPERVISED + MEDIUM → auto si score shadow suffisant
        if mode_val == "SUPERVISED" and risk_upper == "MEDIUM":
            return shadow_score >= _SUPERVISED_MEDIUM_MIN_SCORE

        return base

    def requires_validation(self, risk: str, shadow_score: float = 0.0) -> bool:
        """Inverse de should_auto_approve."""
        return not self.should_auto_approve(risk, shadow_score)

    def mode_description(self) -> str:
        """Description lisible du mode actuel."""
        descriptions = {
            SystemMode.MANUAL: (
                "MANUAL — Validation requise pour toute action."
            ),
            SystemMode.SUPERVISED: (
                "SUPERVISED — LOW auto / MEDIUM auto si score≥7 / HIGH+CRITICAL : validation."
            ),
            SystemMode.AUTO: (
                "AUTO — Bea agit seul. Seules les actions CRITICAL demandent validation."
            ),
        }
        return descriptions[self._mode]

    def to_dict(self) -> dict:
        return {
            "mode":        self._mode.value,
            "description": self.mode_description(),
            "changed_at":  self._changed_at,
            "changed_by":  self._changed_by,
            "rules": {
                "LOW":      "auto" if self.should_auto_approve("LOW") else "manual",
                "MEDIUM":   "auto" if self.should_auto_approve("MEDIUM", 10.0) else "manual",
                "HIGH":     "auto" if self.should_auto_approve("HIGH") else "manual",
                "CRITICAL": "auto" if self.should_auto_approve("CRITICAL") else "manual",
            },
        }

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text("utf-8"))
            mode_str = data.get("mode", "SUPERVISED")
            self._mode       = SystemMode(mode_str)
            self._changed_at = data.get("changed_at", time.time())
            self._changed_by = data.get("changed_by", "system")
        except Exception as exc:
            log.warning("mode_system_load_failed", err=str(exc))

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "mode":       self._mode.value,
                "changed_at": self._changed_at,
                "changed_by": self._changed_by,
            }
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception as exc:
            log.warning("mode_system_save_failed", err=str(exc))


# ── Singleton ─────────────────────────────────────────────────────────────────

_mode_instance: ModeSystem|None = None


def get_mode_system() -> ModeSystem:
    global _mode_instance
    if _mode_instance is None:
        _mode_instance = ModeSystem()
    return _mode_instance
