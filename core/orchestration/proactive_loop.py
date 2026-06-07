"""
proactive_loop.py — Boucle d'initiative asynchrone pour BeaMax
Architecture d'autonomie graduée — Niveau 2

Gère le cycle proactif : détection → évaluation du risque → action ou signal.
S'intègre avec HEARTBEAT.md et GoalRegistry.

Auteur: Bea (BeaMax Research)
Date: 2026-04-09
"""

from __future__ import annotations

import asyncio
import logging
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from core.orchestration.goal_registry import ProactiveGoal, GoalRegistry

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

CYCLE_INTERVAL_SECONDS = 30 * 60   # 30 minutes


def _resolve_workspace_paths() -> tuple[Path, Path]:
    """Resolve heartbeat + workspace paths via config.settings.

    The original module-level constants were hardcoded to
    /root/.openclaw-bestclaw/workspace/* which broke non-root hosts and
    CI runners. Audit S7 (2026-05-19): defer the path resolution behind
    a function so the heavy import side-effect is avoided, and so the
    paths follow whatever workspace_dir the settings layer resolves at
    runtime.
    """
    try:
        from config.settings import get_settings
        ws = Path(get_settings().workspace_dir)
    except Exception:
        ws = Path.home() / ".beamax" / "workspace"
    return ws / "HEARTBEAT.md", ws


HEARTBEAT_PATH, WORKSPACE = _resolve_workspace_paths()


# ── Types de données ──────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    NONE = "none"         # Lecture pure — toujours OK
    SAFE = "safe"         # Écriture notes, logs — fait + informe
    MODERATE = "moderate" # Message, API externe — propose + attend
    HIGH = "high"         # Suppression, modification critique — confirmation
    CRITICAL = "critical" # Irréversible — double confirmation obligatoire


@dataclass
class ProactiveAction:
    """Une action détectée ou exécutée par le ProactiveAgent."""

    goal_id: str
    description: str
    risk: RiskLevel
    executed: bool = False
    result: Optional[dict] = None
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "risk": self.risk.value,
            "executed": self.executed,
            "result": self.result,
            "timestamp": self.timestamp,
            "error": self.error,
        }


# ── Matrice de calibration ────────────────────────────────────────────────────

RISK_PATTERNS: list[tuple[list[str], RiskLevel]] = [
    # Mots-clés → niveau de risque
    (["delete", "rm", "supprimer", "effacer", "drop"],          RiskLevel.HIGH),
    (["send", "email", "tweet", "message", "post", "envoyer"],  RiskLevel.MODERATE),
    (["write", "create", "update", "écrire", "créer", "noter"], RiskLevel.SAFE),
    (["read", "check", "status", "lire", "vérifier"],           RiskLevel.NONE),
    (["format", "wipe", "truncate", "destroy", "irréversible"], RiskLevel.CRITICAL),
]

AUTONOMY_MATRIX = {
    RiskLevel.NONE:     ("Fait sans demander",              True),
    RiskLevel.SAFE:     ("Fait + informe Unity",            True),
    RiskLevel.MODERATE: ("Propose + attend validation",     False),
    RiskLevel.HIGH:     ("Demande confirmation explicite",  False),
    RiskLevel.CRITICAL: ("Refuse sans double confirmation", False),
}


# ── ProactiveAgent ────────────────────────────────────────────────────────────

class ProactiveAgent:
    """
    Boucle d'initiative asynchrone.

    Usage:
        agent = ProactiveAgent(registry)
        await agent.start()          # démarre la boucle infinie
        actions = await agent.run_cycle()   # un cycle manuel
    """

    def __init__(
        self,
        registry: Optional[GoalRegistry] = None,
        cycle_interval: int = CYCLE_INTERVAL_SECONDS,
        dry_run: bool = False,
    ) -> None:
        self.registry = registry or GoalRegistry()
        self.cycle_interval = cycle_interval
        self.dry_run = dry_run
        self._running = False
        self._action_log: list[ProactiveAction] = []

    # ── Boucle principale ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Démarre la boucle proactive (bloquant)."""
        self._running = True
        logger.info("ProactiveAgent démarré — cycle toutes les %ds", self.cycle_interval)
        while self._running:
            try:
                actions = await self.run_cycle()
                if actions:
                    self._update_heartbeat(actions)
            except Exception as exc:  # noqa: BLE001
                logger.error("Erreur cycle proactif : %s", exc)
            await asyncio.sleep(self.cycle_interval)

    def stop(self) -> None:
        self._running = False

    async def run_forever(self, interval_seconds: int = CYCLE_INTERVAL_SECONDS) -> None:
        """Alias de start() avec override optionnel de l'intervalle."""
        self.cycle_interval = interval_seconds
        await self.start()

    async def run_cycle(self) -> list[ProactiveAction]:
        """
        Exécute un cycle complet :
          1. Collecte le contexte environnemental
          2. Détecte les opportunités d'action
          3. Évalue le risque de chaque action candidate
          4. Exécute les actions sûres, signale les autres
        """
        context = await self._collect_context()
        opportunities = self.registry.detect_opportunity(context)

        if not opportunities:
            logger.debug("Aucune opportunité détectée ce cycle")
            return []

        actions: list[ProactiveAction] = []

        for goal in opportunities:
            action = self._build_action(goal, context)
            if action is None:
                continue

            if self.should_act_now(goal, context):
                if AUTONOMY_MATRIX[action.risk][1]:  # auto-exécutable ?
                    action = await self._execute_action(action)
                else:
                    action.description = f"[SIGNAL] {action.description}"
                    logger.info(
                        "Action signalée (risque %s) : %s",
                        action.risk.value,
                        action.description,
                    )
            else:
                action.description = f"[REPORT] {action.description}"

            self._action_log.append(action)
            actions.append(action)

            # Met à jour last_checked
            self.registry.update_progress(
                goal.id,
                goal.progress,
                notes=f"Cycle proactif — {action.description[:80]}",
            )

        return actions

    # ── Évaluation ────────────────────────────────────────────────────────────

    def assess_risk(self, action_description: str) -> RiskLevel:
        """
        Détermine le niveau de risque d'une action en analysant sa description.
        Utilise la matrice de patterns par mots-clés.
        """
        desc_lower = action_description.lower()
        for keywords, risk in RISK_PATTERNS:
            if any(kw in desc_lower for kw in keywords):
                return risk
        return RiskLevel.SAFE  # défaut conservateur

    def should_act_now(self, goal: ProactiveGoal, context: dict) -> bool:
        """
        Décide si Bea doit agir maintenant (vs juste signaler).

        Critères :
        - Priorité haute (≥7) → agir
        - Objectif immédiat → agir
        - Service critique down → agir
        - Heure de travail (8h-22h) → agir
        - Paused ou hors fenêtre → ne pas agir
        """
        if goal.paused:
            return False
        if goal.priority >= 7:
            return True
        if goal.horizon == "immediate":
            return True
        hour = context.get("hour", 12)
        if hour < 8 or hour > 22:
            return False
        if goal.horizon in ("weekly", "monthly") and goal.staleness_hours() > 2:
            return True
        return False

    # ── Exécution ─────────────────────────────────────────────────────────────

    async def execute_safe_action(self, action_description: str) -> dict:
        """
        Exécute une action de niveau NONE ou SAFE.
        Toute autre action lève une ValueError.
        """
        risk = self.assess_risk(action_description)
        if risk not in (RiskLevel.NONE, RiskLevel.SAFE):
            raise ValueError(
                f"Action refusée : risque '{risk.value}' trop élevé pour l'autonomie niveau 2. "
                f"Action : {action_description}"
            )

        if self.dry_run:
            return {"status": "dry_run", "action": action_description}

        # Actions sûres supportées nativement
        if action_description.startswith("read_file:"):
            path = action_description.split(":", 1)[1].strip()
            return self._read_file_safe(path)

        if action_description.startswith("write_note:"):
            payload = action_description.split(":", 1)[1].strip()
            return self._write_note(payload)

        if action_description.startswith("shell_readonly:"):
            cmd = action_description.split(":", 1)[1].strip()
            return self._run_readonly_shell(cmd)

        return {"status": "no_handler", "action": action_description}

    async def _execute_action(self, action: ProactiveAction) -> ProactiveAction:
        """Tente d'exécuter l'action et documente le résultat."""
        try:
            result = await self.execute_safe_action(action.description)
            action.executed = True
            action.result = result
            logger.info("✅ Action exécutée : %s → %s", action.description[:60], result)
        except ValueError as exc:
            action.error = str(exc)
            logger.warning("⚠️  Action bloquée : %s", exc)
        except Exception as exc:  # noqa: BLE001
            action.error = f"Erreur inattendue : {exc}"
            logger.error("❌ Échec action : %s", exc)
        return action

    # ── Collecte de contexte ──────────────────────────────────────────────────

    async def _collect_context(self) -> dict:
        """
        Collecte l'état courant de l'environnement pour alimenter detect_opportunity.
        """
        context: dict = {
            "hour": int(time.strftime("%H")),
            "timestamp": time.time(),
            "services_down": [],
            "files_changed": [],
            "deadlines_soon": [],
        }

        # Vérification services systemd (lecture seule = risque nul)
        context["services_down"] = await self._check_services_down()

        # Fichiers récemment modifiés (dernières 30 min)
        context["files_changed"] = self._detect_recent_changes(minutes=30)

        # Deadlines proches
        context["deadlines_soon"] = self._check_upcoming_deadlines(hours=24)

        return context

    async def _check_services_down(self) -> list[str]:
        """Liste les services systemd qui sont down (lecture seule)."""
        known_services = ["bea_core", "caddy", "postgresql", "redis"]
        down: list[str] = []
        for svc in known_services:
            try:
                result = subprocess.run(  # nosec B603 B607
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=3
                )
                if result.stdout.strip() != "active":
                    down.append(svc)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                logger.debug("swallowed_exception", exc_info=True)
        return down

    def _detect_recent_changes(self, minutes: int = 30) -> list[str]:
        """Détecte les fichiers modifiés récemment dans le workspace."""
        changed: list[str] = []
        cutoff = time.time() - minutes * 60
        watch_dirs = [WORKSPACE / "docs", WORKSPACE / "lab"]
        for d in watch_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.md"):
                if f.stat().st_mtime > cutoff:
                    changed.append(str(f))
        return changed

    def _check_upcoming_deadlines(self, hours: int = 24) -> list[str]:
        """Retourne les IDs d'objectifs dont la deadline approche."""
        soon: list[str] = []
        for goal in self.registry.get_active_goals():
            dl = goal.deadline_hours()
            if dl is not None and 0 < dl <= hours:
                soon.append(goal.id)
        return soon

    # ── Construction d'action ─────────────────────────────────────────────────

    def _build_action(self, goal: ProactiveGoal, context: dict) -> Optional[ProactiveAction]:
        """Construit l'action appropriée en fonction du goal et du contexte."""
        services_down = context.get("services_down", [])
        files_changed = context.get("files_changed", [])

        if "monitoring" in goal.tags and services_down:
            desc = f"write_note:⚠️ Services down détectés : {', '.join(services_down)}"
            return ProactiveAction(goal_id=goal.id, description=desc, risk=RiskLevel.SAFE)

        if "documentation" in goal.tags and files_changed:
            desc = f"write_note:📝 Fichiers modifiés à documenter : {files_changed[0]}"
            return ProactiveAction(goal_id=goal.id, description=desc, risk=RiskLevel.SAFE)

        dl = goal.deadline_hours()
        if dl is not None and 0 < dl <= 24:
            desc = f"write_note:⏰ Deadline dans {dl:.1f}h pour : {goal.description[:60]}"
            return ProactiveAction(goal_id=goal.id, description=desc, risk=RiskLevel.SAFE)

        if goal.horizon == "immediate" and goal.staleness_hours() > 0.25:
            desc = f"shell_readonly:echo 'check: {goal.id}'"
            return ProactiveAction(goal_id=goal.id, description=desc, risk=RiskLevel.NONE)

        return None

    # ── Actions sûres ─────────────────────────────────────────────────────────

    def _read_file_safe(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"status": "not_found", "path": path}
        content = p.read_text(errors="replace")[:2000]
        return {"status": "ok", "path": path, "content": content}

    def _write_note(self, payload: str) -> dict:
        note_file = WORKSPACE / "lab" / "proactive_notes.md"
        note_file.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        with note_file.open("a", encoding="utf-8") as f:
            f.write(f"\n## {ts}\n{payload}\n")
        return {"status": "written", "file": str(note_file)}

    def _run_readonly_shell(self, cmd: str) -> dict:
        """Exécute une commande shell en lecture seule (whitelist stricte, shell=False)."""
        import shlex
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            return {"status": "blocked", "reason": f"parse_error: {e}", "cmd": cmd}
        if not args:
            return {"status": "blocked", "reason": "empty", "cmd": cmd}
        ALLOWED = {"echo", "cat", "ls", "df", "free", "uptime"}
        if args[0] not in ALLOWED:
            return {"status": "blocked", "reason": "commande non autorisée", "cmd": cmd}
        try:
            result = subprocess.run(  # nosec B603 B607
                args, shell=False, capture_output=True, text=True, timeout=5
            )
            return {"status": "ok", "stdout": result.stdout[:500], "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "cmd": cmd}

    # ── Intégration HEARTBEAT.md ──────────────────────────────────────────────

    def _update_heartbeat(self, actions: list[ProactiveAction]) -> None:
        """Enrichit HEARTBEAT.md avec les actions proactives du cycle."""
        if not actions:
            return

        section_header = "\n## 🤖 Proactive Actions (Auto-updated)\n"
        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        lines = [section_header, f"_Last cycle: {ts}_\n\n"]

        for action in actions[:5]:  # max 5 items pour ne pas surcharger
            icon = "✅" if action.executed else "📢"
            lines.append(f"- {icon} [{action.risk.value.upper()}] {action.description[:100]}\n")

        # Objectifs actifs
        active = self.registry.get_active_goals()
        if active:
            lines.append("\n## 📋 Active Goals\n")
            for g in active[:3]:
                pct = int(g.progress * 100)
                lines.append(f"- P{g.priority} [{pct}%] {g.description[:60]}\n")

        new_section = "".join(lines)

        if HEARTBEAT_PATH.exists():
            content = HEARTBEAT_PATH.read_text()
            # Remplace l'ancienne section si elle existe
            marker = "## 🤖 Proactive Actions"
            if marker in content:
                content = content[:content.index(marker)] + new_section
            else:
                content += new_section
        else:
            content = f"# HEARTBEAT.md\n{new_section}"

        HEARTBEAT_PATH.write_text(content)
        logger.info("HEARTBEAT.md mis à jour avec %d actions", len(actions))

    # ── Rapport ───────────────────────────────────────────────────────────────

    def last_cycle_report(self) -> str:
        if not self._action_log:
            return "Aucune action exécutée ce cycle."
        lines = ["## Rapport cycle proactif\n"]
        for a in self._action_log[-10:]:
            status = "✅" if a.executed else ("❌" if a.error else "📢")
            lines.append(
                f"{status} [{a.risk.value}] {a.description[:80]}\n"
                + (f"   Erreur : {a.error}\n" if a.error else "")
            )
        return "".join(lines)


# ── Point d'entrée CLI ────────────────────────────────────────────────────────

async def _main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    registry = GoalRegistry()

    # Objectifs de démo si vide
    if not registry.get_active_goals():
        g1 = registry.create_goal(
            "Surveiller la santé des services BeaMax",
            horizon="permanent", priority=9, tags=["monitoring"],
            next_action="Vérifier systemctl status des services core",
        )
        g2 = registry.create_goal(
            "Maintenir la documentation à jour",
            horizon="weekly", priority=6, tags=["documentation"],
            next_action="Scanner les fichiers modifiés dans /docs",
        )
        g3 = registry.create_goal(
            "Rappeler les deadlines critiques",
            horizon="weekly", priority=8, tags=["deadline"],
            next_action="Vérifier la liste des deadlines actives",
        )
        # Simuler une deadline dans 12h
        g3.set_deadline(time.time() + 12 * 3600)
        registry.save()
        print(f"Objectifs de démo créés : {g1.id}, {g2.id}, {g3.id}")

    agent = ProactiveAgent(registry, cycle_interval=CYCLE_INTERVAL_SECONDS, dry_run=False)

    print("Démarrage d'un cycle de test...")
    actions = await agent.run_cycle()
    print(agent.last_cycle_report())
    print(registry.summary())
    print(f"\n{len(actions)} action(s) générée(s) ce cycle.")


if __name__ == "__main__":
    asyncio.run(_main())
