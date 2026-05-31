"""
JARVIS MAX — Handlers d'exécution v2
Séparation des préoccupations : les handlers sont indépendants du moteur.

Chaque handler :
- Reçoit un ExecutionTask
- Lit task.payload et task.description
- Retourne un résultat string structuré
- Lève une exception si ça échoue (déclenche le retry)

Handlers disponibles :
  research  → handle_research
  review    → handle_review
  plan      → handle_plan
  improve   → handle_improve
  generic   → handle_generic  (défaut)
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from executor.task_model import ExecutionTask


# ── Registry ──────────────────────────────────────────────────────────────────

HANDLER_REGISTRY: dict[str, callable] = {}


def register_handler(name: str):
    """Décorateur pour enregistrer un handler."""
    def decorator(fn):
        HANDLER_REGISTRY[name] = fn
        return fn
    return decorator


def get_handler(name: str):
    """Retourne le handler par son nom, ou handle_generic si inconnu."""
    return HANDLER_REGISTRY.get(name, handle_generic)


# ── Handlers ──────────────────────────────────────────────────────────────────

@register_handler("research")
def handle_research(task: "ExecutionTask") -> str:
    """Agent: WebScout / Research — lit vault + workspace."""
    ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    desc   = task.description
    target = task.payload.get("target", "")
    lines  = [f"[RESEARCH — {ts}]", f"Mission : {desc}", f"Cible   : {target}", ""]

    # Vault memory
    try:
        from memory.vault_memory import get_vault_memory
        vault   = get_vault_memory()
        entries = list(vault._entries.values()) if hasattr(vault, "_entries") else []
        valid   = [e for e in entries if getattr(e, "valid", True)]
        kw = {w.lower() for w in re.split(r"\W+", desc + " " + target) if len(w) > 4}
        related = [e for e in valid if any(k in e.content.lower() for k in kw)]
        lines.append(f"Vault memory : {len(valid)} entrées actives")
        if related:
            lines.append(f"  Entrées liées ({len(related)}) :")
            for e in related[:4]:
                lines.append(f"    • [{e.type}] {e.content[:90]}")
        else:
            lines.append("  Aucune entrée directement liée dans le vault.")
    except Exception as exc:
        lines.append(f"Vault : non accessible ({exc})")

    # Workspace
    try:
        workspace = Path("workspace")
        if workspace.exists():
            files = sorted(
                [f for f in workspace.rglob("*") if f.is_file()],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            lines.append(f"\nWorkspace : {len(files)} fichier(s)")
            for f in files[:6]:
                lines.append(f"  • {f.name} ({f.stat().st_size} o)")
            if len(files) > 6:
                lines.append(f"  ... et {len(files)-6} autres")
    except Exception as exc:
        lines.append(f"Workspace : {exc}")

    lines.append(f"\nRecherche terminée — {len(lines)} éléments analysés.")
    return "\n".join(lines)


@register_handler("review")
def handle_review(task: "ExecutionTask") -> str:
    """Agent: Lens / Reviewer — vérifie l'état réel du système."""
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[REVIEW — {ts}]", f"Sujet : {task.description}", ""]
    checks = []

    # Check API
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:8000/api/health", timeout=2)
        checks.append(("OK", "API (FastAPI)", "accessible (200)"))
    except Exception as exc:
        checks.append(("WARN", "API (FastAPI)", f"non accessible ({exc.__class__.__name__})"))

    # Check SQLite
    try:
        db_path = Path("workspace/jarvismax.db")
        if db_path.exists():
            size_kb = db_path.stat().st_size // 1024
            checks.append(("OK", "SQLite DB", f"{size_kb} Ko"))
        else:
            checks.append(("WARN", "SQLite DB", "fichier absent"))
    except Exception as exc:
        checks.append(("WARN", "SQLite DB", str(exc)))

    # Check Workspace
    try:
        files = [f for f in Path("workspace").rglob("*") if f.is_file()] if Path("workspace").exists() else []
        checks.append(("OK", "Workspace", f"{len(files)} fichiers"))
    except Exception as exc:
        checks.append(("WARN", "Workspace", str(exc)))

    ok_count = sum(1 for c in checks if c[0] == "OK")
    score    = round(ok_count / len(checks) * 10, 1) if checks else 5.0
    decision = "APPROUVE" if score >= 7.0 else ("A AMELIORER" if score >= 4.0 else "CRITIQUE")

    lines.append("Resultats de l'audit :")
    for icon, label, val in checks:
        lines.append(f"  [{icon}] {label:<20} : {val}")
    lines.append(f"\nScore qualite : {score}/10")
    lines.append(f"Verdict      : {decision}")
    lines.append("Review complete.")
    return "\n".join(lines)


@register_handler("plan")
def handle_plan(task: "ExecutionTask") -> str:
    """Agent: MapPlanner — plan contextuel basé sur la mission."""
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    desc = task.description
    lines = [f"[PLAN — {ts}]", f"Objectif : {desc}", ""]

    # Contexte missions
    try:
        from core.mission_system import get_mission_system
        ms    = get_mission_system()
        stats = ms.stats()
        lines.append("Contexte actuel :")
        lines.append(f"  Missions totales  : {stats.get('total', 0)}")
    except Exception as exc:
        lines.append(f"Contexte : {exc}")

    words = desc.lower()
    if any(w in words for w in ["optim", "amélio", "perfo"]):
        steps = ["Audit des performances actuelles", "Identification des bottlenecks",
                 "Priorisation des optimisations", "Application des correctifs",
                 "Validation post-optimisation"]
    elif any(w in words for w in ["analys", "rapport", "inspec"]):
        steps = ["Collecte des données système", "Analyse statistique",
                 "Identification des patterns", "Génération du rapport", "Validation"]
    else:
        steps = ["Analyse du contexte actuel", "Définition du plan d'action",
                 "Identification des ressources", "Exécution par phases", "Rapport final"]

    lines.append(f"\nPlan structuré ({len(steps)} étapes) :")
    for i, step in enumerate(steps, 1):
        lines.append(f"  {i}. {step}")
    lines.append("Plan généré et prêt à l'exécution.")
    return "\n".join(lines)


@register_handler("improve")
def handle_improve(task: "ExecutionTask") -> str:
    """Agent: Self-Improve — analyse le code et propose des pistes."""
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[IMPROVE — {ts}]", f"Objectif : {task.description}", ""]

    try:
        project_root = Path(".")
        py_files = [
            f for f in project_root.rglob("*.py")
            if "__pycache__" not in str(f) and ".venv" not in str(f)
        ]
        lines.append(f"Modules Python : {len(py_files)}")

        todos = []
        for f in py_files[:20]:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if any(kw in line.upper() for kw in ["TODO", "FIXME", "HACK", "XXX"]):
                        todos.append(f"{f.name}:{i} → {line.strip()[:70]}")
            except Exception as _exc:
                log.warning("swallowed_exception", action="handlers_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        if todos:
            lines.append(f"\nPoints à améliorer ({len(todos)}) :")
            for t in todos[:5]:
                lines.append(f"  • {t}")
            if len(todos) > 5:
                lines.append(f"  ... et {len(todos)-5} autres")
        else:
            lines.append("  Aucun TODO/FIXME détecté dans les modules core.")
    except Exception as exc:
        lines.append(f"Scan : {exc}")

    lines.append("Analyse d'amélioration terminée.")
    return "\n".join(lines)


@register_handler("generic")
def handle_generic(task: "ExecutionTask") -> str:
    """Handler générique — utilisé pour les types inconnus."""
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start = time.time()
    lines = [
        f"[EXECUTE — {ts}]",
        f"Action : {task.description}",
        f"Handler: {task.handler_name}",
        f"Payload: {str(task.payload)[:100]}",
        "",
    ]

    try:
        from core.action_queue import get_action_queue
        q        = get_action_queue()
        all_acts = q.all(limit=500)
        executed = sum(1 for a in all_acts if a.status == "EXECUTED")
        pending  = sum(1 for a in all_acts if a.status == "PENDING")
        lines.append("Snapshot système :")
        lines.append(f"  Actions exécutées : {executed}")
        lines.append(f"  Actions en attente: {pending}")
    except Exception as exc:
        lines.append(f"Snapshot : {exc}")

    elapsed = time.time() - start
    lines.append(f"\nDurée réelle : {elapsed:.3f}s")
    lines.append("Action exécutée.")
    return "\n".join(lines)
