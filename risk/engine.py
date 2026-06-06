"""
JARVIS MAX - Risk Engine
Classifie chaque action : LOW / MEDIUM / HIGH.
Importe RiskLevel depuis core.state (source unique).

LOW    -> execution auto
MEDIUM -> validation via API (requires approval)
HIGH   -> validation obligatoire + backup
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# SOURCE UNIQUE - ne pas redefinir RiskLevel ici
from core.state import RiskLevel


# ══════════════════════════════════════════════════════════════
# RISK REPORT
# ══════════════════════════════════════════════════════════════

@dataclass
class RiskReport:
    level:               RiskLevel
    action_type:         str
    target:              str
    estimated_impact:    str
    backup_required:     bool       = False
    reversible:          bool       = True
    requires_validation: bool       = False
    reasons:             list[str]  = field(default_factory=list)

    @property
    def emoji(self) -> str:
        return {"low": "OK", "medium": "!!!", "high": "DANGER"}[self.level.value]

    def format_card(self) -> str:
        emoji_map = {"low": "Green", "medium": "Yellow", "high": "Red"}
        e = emoji_map.get(self.level.value, "?")
        lines = [
            f"[{e}] Risque {self.level.value.upper()}",
            f"Type : {self.action_type}",
            f"Cible : {self.target[:80]}",
            f"Impact : {self.estimated_impact[:120]}",
            f"Backup : {'prevu' if self.backup_required else 'non'}",
            f"Reversible : {'oui' if self.reversible else 'NON - IRREVERSIBLE'}",
        ]
        if self.reasons:
            lines.append(f"Raisons : {', '.join(self.reasons)}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# PATTERNS DE CLASSIFICATION
# ══════════════════════════════════════════════════════════════

# Commandes shell HIGH RISK - destruction / privileges
_HIGH_CMD = re.compile(
    r"(\brm\s+(-rf?|-r)\s*[/~]|"           # rm -rf /
    r"\bsudo\b|"                             # sudo
    r"\bchmod\b|\bchown\b|"                  # permissions
    r"\bsystemctl\s+(start|stop|restart|enable|disable)\b|"
    r"\bdocker\s+(restart|stop|kill|rm|rmi)\b|"
    r"\bapt(-get)?\s+(install|remove|purge|autoremove)\b|"
    r"\bpip3?\s+install\b|"                  # installation packages
    r"\bcurl\b.+\|\s*(sh|bash)\b|"          # pipe vers shell
    r"\bwget\b.+\|\s*(sh|bash)\b|"
    r"\bmkfs\b|\bfdisk\b|\bdd\s+if=\b|"    # disk ops
    r"\biptables\b|\bufw\b|"                # firewall
    r"\bshutdown\b|\breboot\b|\bhalt\b|"
    r"\bkill\s+-9\b|"
    r"\bpasswd\b|\badduser\b|\buseradd\b|\buserdel\b|"
    r">\s*/etc/|>>\s*/etc/|"               # ecriture /etc
    r"\bssh\b.+@|"                          # connexion SSH
    r"\bscp\b|\brsync\b|"
    r"\bpython3?\s+-c\b)",                  # code arbitraire inline
    re.IGNORECASE,
)

# Commandes MEDIUM RISK - modification sans privileges
_MED_CMD = re.compile(
    r"(\bmv\s+\S+\s+\S+|"                  # deplacer
    r"\bcp\s+-r\b|"                         # copie recursive
    r"\bmkdir\s+(-p\s+)?\S+|"
    r"\bfind\b.+(-delete|-exec\s+rm)\b|"   # find + delete
    r"\bpython3?\s+\S+\.py|"               # executer script
    r"\bbash\s+\S+\.sh|\bsh\s+\S+\.sh|"
    r"\bgit\s+(commit|push|merge|reset|rebase|checkout\s+-b)\b|"
    r"\bnpm\s+(install|run)\b|\byarn\b|"
    r"\bdocker\s+(build|run|exec)\b|"
    r"\bcurl\b|\bwget\b)",                  # requetes reseau
    re.IGNORECASE,
)

# Chemins systeme protégés
_SYS_PATHS = re.compile(
    r"(/etc/|/usr/|/bin/|/sbin/|/boot/|/sys/|/proc/|/root/|"
    r"\.ssh/|\.bashrc|\.zshrc|\.profile|\.bash_profile|"
    r"/var/lib/|/lib/|/lib64/|"
    r"\.env$|docker-compose\.yml$|Dockerfile$)",
    re.IGNORECASE,
)

# Fichiers de config sensibles
_CONFIG_FILES = re.compile(
    r"\.(env|secret|key|pem|crt|p12|pfx|htpasswd)$|"
    r"(secret|credential|password|token|api.?key)",
    re.IGNORECASE,
)

# Repertoires core Jarvis
_CORE_DIRS = (
    "core/", "agents/", "risk/", "executor/",
    "night_worker/", "self_improve/", "jarvis_bot/",
    "tools/", "observer/", "memory/", "config/",
)

WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))


# ══════════════════════════════════════════════════════════════
# RISK ENGINE
# ══════════════════════════════════════════════════════════════

class RiskEngine:
    """
    Classifie une action en LOW / MEDIUM / HIGH.
    Utilise RiskLevel de core.state (source unique).
    """

    def analyze(
        self,
        action_type: str,
        target: str = "",
        content: str = "",
        command: str = "",
        old_str: str = "",
        new_str: str = "",
    ) -> RiskReport:

        at = action_type.lower().strip()

        # ── 1. Lecture pure → LOW ─────────────────────────────
        if at in {
            "read_file", "list_dir", "analyze_dir",
            "read_directory",                          # lecture répertoire
            "generate_report", "analyze_system",
            "generate_code", "generate_script",
            "draft_content", "prepare_report",
            "analyze_logs", "snapshot_workspace",
        }:
            return self._low(at, target, "Lecture seule - aucune modification")

        # ── 2. Backup → LOW ───────────────────────────────────
        if at == "backup_file":
            return self._low(at, target, "Copie de securite - non destructif")

        # ── 3. Config / secrets → HIGH ────────────────────────
        if target and _CONFIG_FILES.search(target):
            return self._high(at, target,
                              "Fichier de configuration sensible",
                              reversible=False, backup=True,
                              reasons=["Fichier secrets / credentials"])

        # 3b. Fichiers config Jarvis proteges -> HIGH
        _JARVIS_CONFIG_FILES = frozenset({
            "config/settings.py", ".env", "docker-compose.yml",
            "risk/engine.py", "self_improve/engine.py",
        })
        if target and any(
            target == f or target.endswith("/" + f) or target.endswith(os.sep + f)
            for f in _JARVIS_CONFIG_FILES
        ):
            return self._high(at, target,
                              "Fichier de configuration Jarvis protege",
                              reversible=False, backup=True,
                              reasons=["Config / guard-rails Jarvis"])

        # ── 4. Chemins systeme → HIGH ─────────────────────────
        if target and _SYS_PATHS.search(target):
            return self._high(at, target,
                              "Ecriture dans chemin systeme protege",
                              reversible=False, backup=True,
                              reasons=["Chemin systeme /etc /usr /bin..."])

        # ── 5. Creation dans workspace → LOW ──────────────────
        if at in {"create_file", "write_file"} and target:
            if self._in_workspace(target):
                return self._low(at, target, "Creation dans zone libre workspace")
            return self._medium(at, target,
                                "Creation hors workspace",
                                reasons=["Cible hors zone workspace"])

        # ── 6. Commandes shell ────────────────────────────────
        if at == "run_command" and command:
            cmd = command.strip()
            if _HIGH_CMD.search(cmd):
                return self._high(at, cmd,
                                  "Commande systeme dangereuse",
                                  reversible=False, backup=True,
                                  reasons=["Pattern HIGH RISK detecte"])
            if _MED_CMD.search(cmd):
                return self._medium(at, cmd,
                                    "Commande avec effets de bord potentiels",
                                    reasons=["Pattern MEDIUM RISK detecte"])
            # Commande courte et simple
            return self._low(at, cmd, "Commande simple - lecture estimee")

        # ── 7. Replace in file ────────────────────────────────
        if at == "replace_in_file":
            if target and _CONFIG_FILES.search(target):
                return self._high(at, target,
                                  "Modification fichier config sensible",
                                  reversible=False, backup=True,
                                  reasons=["Config / secrets"])
            if target and _SYS_PATHS.search(target):
                return self._high(at, target,
                                  "Modification fichier systeme",
                                  reversible=False, backup=True,
                                  reasons=["Chemin systeme protege"])
            if target and self._is_core(target):
                return self._medium(at, target,
                                    "Patch sur code core Jarvis",
                                    backup=True,
                                    reasons=["Modification core - backup requis"])
            if target and self._in_workspace(target):
                return self._low(at, target,
                                 "Modification dans workspace")
            return self._medium(at, target,
                                "Modification fichier externe",
                                backup=True,
                                reasons=["Hors workspace"])

        # ── 8. Suppression → HIGH ─────────────────────────────
        if at in {"delete_file", "delete_dir", "remove"}:
            return self._high(at, target,
                              "Suppression de fichier / repertoire",
                              reversible=False, backup=True,
                              reasons=["Irreversible sans backup"])

        # ── 8b. Actions supervisées avancées ─────────────────
        if at in {"run_python_script", "create_workflow", "schedule_task"}:
            return self._medium(at, target,
                                f"Action supervisée {at}",
                                reasons=[f"Exécution contrôlée : {at}"])

        # ── 9. Deplacement → MEDIUM ───────────────────────────
        if at in {"move_file", "copy_file"}:
            return self._medium(at, target,
                                "Modification d arborescence",
                                reasons=["Deplacement ou copie"])

        # ── 10. Reseau externe → HIGH ─────────────────────────
        if at in {"http_request", "api_call", "external_request",
                  "send_email", "webhook_call", "post_data"}:
            return self._high(at, target,
                              "Communication avec service externe",
                              reasons=["Envoi de donnees vers l exterieur"])

        # ── 11. Installation → HIGH ───────────────────────────
        if at in {"install_package", "pip_install", "apt_install",
                  "npm_install", "brew_install"}:
            return self._high(at, target,
                              "Installation de logiciel",
                              reasons=["Modification de l environnement systeme"])

        # ── 12. Execution de patch / script → HIGH ────────────
        if at in {"apply_patch", "run_patch", "exec_script"}:
            return self._high(at, target,
                              "Execution de patch ou script",
                              backup=True,
                              reasons=["Modification potentiellement irreversible"])

        # ── Fallback → MEDIUM ─────────────────────────────────
        return self._medium(at, target,
                            "Impact non classe",
                            reasons=[f"Type non connu : {at}"])

    # ── Constructeurs ─────────────────────────────────────────

    def _low(self, at: str, t: str, impact: str) -> RiskReport:
        return RiskReport(
            level=RiskLevel.LOW, action_type=at, target=t,
            estimated_impact=impact,
            requires_validation=False,
        )

    def _medium(self, at: str, t: str, impact: str,
                backup: bool = False,
                reasons: list[str] | None = None) -> RiskReport:
        return RiskReport(
            level=RiskLevel.MEDIUM, action_type=at, target=t,
            estimated_impact=impact, backup_required=backup,
            requires_validation=True, reasons=reasons or [],
        )

    def _high(self, at: str, t: str, impact: str,
              reversible: bool = True, backup: bool = False,
              reasons: list[str] | None = None) -> RiskReport:
        return RiskReport(
            level=RiskLevel.HIGH, action_type=at, target=t,
            estimated_impact=impact, backup_required=backup,
            reversible=reversible, requires_validation=True,
            reasons=reasons or [],
        )

    # ── Helpers ───────────────────────────────────────────────

    def _in_workspace(self, target: str) -> bool:
        try:
            Path(target).resolve().relative_to(WORKSPACE.resolve())
            return True
        except ValueError as _exc:
            log.warning("swallowed_exception", action="engine_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # Chemins relatifs commencant par workspace/
        return target.startswith(("workspace/", "./workspace/"))

    def _is_core(self, target: str) -> bool:
        t = target.replace("\\", "/")
        return any(
            t.startswith(d) or f"/{d}" in t
            for d in _CORE_DIRS
        )

    def classify_bulk(self, actions: list[dict]) -> list[RiskReport]:
        """Classifie une liste d actions en un appel."""
        return [
            self.analyze(
                action_type=a.get("action_type", ""),
                target=a.get("target", ""),
                content=a.get("content", ""),
                command=a.get("command", ""),
            )
            for a in actions
        ]

    def highest_risk(self, reports: list[RiskReport]) -> RiskLevel:
        """Retourne le niveau de risque le plus eleve d une liste."""
        order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        return max(reports, key=lambda r: order[r.level]).level if reports else RiskLevel.LOW
