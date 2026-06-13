"""
BEA MAX - Action Executor
Execute les actions apres validation de risque.
Backup automatique avant toute modification.
Log JSONL complet.
Whitelist elargie pour couvrir les cas reels Bea.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone as _tz
UTC = _tz.utc  # Python 3.10 compat: datetime.UTC added in 3.11
from pathlib import Path

import structlog

from core.state import ActionSpec

log = structlog.get_logger()

def _resolve_workspace() -> Path:
    """Resout WORKSPACE_DIR dynamiquement.
    Priorite : env WORKSPACE_DIR > BEA_ROOT/workspace > detection auto > /app/workspace
    """
    if ws := os.getenv("WORKSPACE_DIR"):
        return Path(ws)
    if root := os.getenv("BEA_ROOT"):
        return Path(root) / "workspace"
    # Detection automatique en dev local (chemin relatif au projet)
    here = Path(__file__).resolve().parent.parent
    candidate = here / "workspace"
    if candidate.exists():
        return candidate
    return Path("/app/workspace")

WORKSPACE  = _resolve_workspace()
BACKUP_DIR = WORKSPACE / ".backups"
LOGS_DIR   = Path(os.getenv("LOGS_DIR", str(WORKSPACE.parent / "logs")))
EXEC_LOG   = LOGS_DIR / "executor.jsonl"

CMD_TIMEOUT = 60  # secondes
AGENT_TIMEOUT_SECONDS = 60  # configurable
_COMMAND_METACHARS = ("|", "&&", "||", ";", ">", "<", "`", "$(", "\n", "\r")


def _workspace_path(raw: str, *, must_exist: bool = False) -> tuple[Path | None, str | None]:
    """Resolve a target inside WORKSPACE. Returns (path, error)."""
    if not raw:
        return WORKSPACE, None
    base = WORKSPACE.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        # Agents commonly describe paths from the repository root as
        # ``workspace/...`` while this executor is already rooted at WORKSPACE.
        # Strip that redundant prefix to avoid writing to workspace/workspace.
        if candidate.parts and candidate.parts[0].lower() == base.name.lower():
            candidate = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path(".")
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError:
        resolved = candidate.parent.resolve() / candidate.name
    if resolved != base and base not in resolved.parents:
        return None, f"outside workspace: {raw}"
    return resolved, None


def _parse_allowed_command(cmd: str) -> tuple[list[str] | None, str | None]:
    if any(meta in cmd for meta in _COMMAND_METACHARS):
        return None, "shell_metacharacters_not_allowed"
    try:
        args = shlex.split(cmd)
    except ValueError as exc:
        return None, f"invalid_command: {exc}"
    if not args:
        return None, "Commande vide"
    return args, None


async def run_with_timeout(coro, timeout=AGENT_TIMEOUT_SECONDS, agent_name=""):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        log.error("executor_agent_timeout", agent=agent_name, timeout=timeout)
        return {"status": "timeout", "result": f"Agent {agent_name} n'a pas répondu dans le délai imparti.", "agent_name": agent_name}
    except Exception as e:
        log.error("executor_agent_error", agent=agent_name, error=str(e))
        return {"status": "error", "result": str(e), "agent_name": agent_name}


# ── Blacklist absolue (jamais executee, meme si approuvee) ─────
_BLACKLIST = re.compile(
    r"(rm\s+-rf\s*/|rm\s+-rf\s*~|"      # rm racine ou home
    r"sudo\s+rm|sudo\s+dd|"
    r"mkfs\.|fdisk\s|"
    r":\s*\(\)\s*\{\s*:\|:\s*&\s*\}|"   # fork bomb
    r">\s*/dev/[sh]d[a-z]|"             # ecriture disque brut
    r"base64\s+--decode.+\|\s*(sh|bash))",
    re.IGNORECASE,
)

# ── Whitelist : commandes autorisees ──────────────────────────
# Couvre les usages reels de Bea : lecture, analyse, python, git
_WHITELIST = re.compile(
    r"^("
    # Lecture systeme
    r"ls(\s+-[lah]+)*(\s+\S+)*|"
    r"cat\s+\S+|head(\s+-n\s*\d+)?\s+\S+|tail(\s+-[nf]\s*\d+)?\s+\S+|"
    r"grep(\s+-[rlniE]+)*\s+\S+.*|"
    r"find\s+\S+(\s+-(name|type|size|mtime)\s+\S+)*|"
    r"wc(\s+-[lwc]+)?\s+\S+|diff(\s+-[uU]\d*)?\s+\S+\s+\S+|"
    r"tree(\s+-L\s+\d+)?(\s+\S+)?|"
    r"echo\s+.*|printf\s+.*|"
    r"pwd|whoami|date|env|"
    r"df(\s+-h)?|du(\s+-sh?)?\s+\S+|"
    r"sort(\s+-[rkn]+)*(\s+\S+)?|uniq(\s+-[cdu]+)?(\s+\S+)?|"
    # Navigation / creation
    r"mkdir(\s+-p)?\s+\S+|"
    r"touch\s+\S+|"
    r"cp(\s+-r)?\s+\S+\s+\S+|"
    r"mv\s+\S+\s+\S+|"
    # Python — scripts dans workspace/ ou scripts/ uniquement
    # python3 -c est EXCLU : classé HIGH par RiskEngine, validation obligatoire
    r"python3?(\s+-[mW]\s+\S+|\s+workspace/\S+\.py(\s+[^;|&<>]*)?|\s+scripts/\S+\.py(\s+[^;|&<>]*)?)|"
    # Git lecture
    r"git\s+(status|log(\s+--\S+)*|diff(\s+\S+)?|show(\s+\S+)?|branch(\s+-[av]+)?|remote(\s+-v)?)\b|"
    # Pip lecture
    r"pip3?(\s+list|\s+show\s+\S+|\s+freeze)(\s+\S+)?|"
    # Qdrant / Redis status
    r"redis-cli(\s+-a\s+\S+)?\s+ping|"
    r"curl(\s+-s)?\s+http://localhost\S*"
    r")$",
    re.IGNORECASE,
)


@dataclass
class ActionResult:  # canonical name for shell/file action results
    success:     bool
    action_type: str
    target:      str
    output:      str
    error:       str | None = None
    backup_path: str | None = None
    duration_ms: int        = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action_type": self.action_type,
            "target": self.target[:200],
            "output": self.output[:2000],
            "error": self.error,
            "backup_path": self.backup_path,
            "duration_ms": self.duration_ms,
        }

    def format_output(self) -> str:
        icon = "OK" if self.success else "ERREUR"
        lines = [
            f"[{icon}] {self.action_type}",
            f"Cible : {self.target[:80]}",
        ]
        if self.backup_path:
            lines.append(f"Backup : {Path(self.backup_path).name}")
        if self.output:
            preview = self.output[:500] + ("..." if len(self.output) > 500 else "")
            lines.append(f"\n{preview}")
        if self.error:
            lines.append(f"Erreur : {self.error[:200]}")
        return "\n".join(lines)

    def is_rejected_by_whitelist(self) -> bool:
        return self.error is not None and "whitelist" in (self.error or "").lower()


# Alias: runner.py used ExecutionResult but only ActionResult is defined here
ExecutionResult = ActionResult


class ActionExecutor:

    def __init__(self, settings=None):
        self.s = settings
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        action: ActionSpec,
        session_id: str = "",
        agent: str = "system",
    ) -> ExecutionResult:
        t0 = time.monotonic()

        handlers = {
            "read_file":       self._read_file,
            "write_file":      self._write_file,
            "create_file":     self._write_file,
            "backup_file":     self._backup_action,
            "replace_in_file": self._replace_in_file,
            "run_command":     self._run_command,
            "list_dir":        self._list_dir,
            "analyze_dir":     self._analyze_dir,
            "delete_file":     self._delete_file,
            "move_file":       self._move_file,
            "copy_file":       self._copy_file,
        }
        handler = handlers.get(action.action_type)

        if not handler:
            result = ExecutionResult(
                False, action.action_type, action.target, "",
                f"Type d action inconnu : '{action.action_type}'. "
                f"Types supportes : {', '.join(handlers.keys())}"
            )
        else:
            try:
                result = await handler(action)
            except Exception as e:
                log.error("executor_unhandled", action=action.action_type, err=str(e))
                result = ExecutionResult(
                    False, action.action_type, action.target, "", str(e)
                )

        result.duration_ms = int((time.monotonic() - t0) * 1000)
        await self._log(result, session_id, agent, action.risk.value if action.risk else "?")

        if result.success:
            log.info("action_executed",
                     type=action.action_type, target=action.target[:60],
                     ms=result.duration_ms)
        else:
            log.warning("action_failed",
                        type=action.action_type, error=result.error[:100] if result.error else "?")

        return result

    # ── Handlers ──────────────────────────────────────────────

    async def _read_file(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target, must_exist=True)
        if path_error:
            return ExecutionResult(False, "read_file", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "read_file", a.target, "",
                                   f"Fichier introuvable : {a.target}")
        if not p.is_file():
            return ExecutionResult(False, "read_file", a.target, "",
                                   f"N est pas un fichier : {a.target}")
        try:
            content = p.read_text("utf-8", errors="replace")
            return ExecutionResult(True, "read_file", a.target, content)
        except PermissionError:
            return ExecutionResult(False, "read_file", a.target, "",
                                   "Permission refusee")

    async def _write_file(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target)
        if path_error:
            return ExecutionResult(False, "write_file", a.target, "", path_error)
        backup = None
        if p.exists():
            backup = await self._backup(p)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(a.content, encoding="utf-8")
        except PermissionError:
            return ExecutionResult(False, "write_file", a.target, "",
                                   "Permission refusee")

        # ── ExecutionGuard : vérification post-écriture ───────────────────────
        try:
            from core.execution_guard import get_guard
            guard_result = await get_guard().guard_write(str(p), a.content)
            if not guard_result.passed:
                return ExecutionResult(
                    False, "write_file", a.target, "",
                    f"[GUARD FAIL] {guard_result.error}",
                    backup_path=backup,
                )
        except Exception as _guard_err:
            log.warning("execution_guard_error",
                        action="write_file", err=str(_guard_err)[:100])

        return ExecutionResult(True, "write_file", a.target,
                               f"Ecrit : {len(a.content)} caracteres",
                               backup_path=backup)

    async def _backup_action(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target, must_exist=True)
        if path_error:
            return ExecutionResult(False, "backup_file", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "backup_file", a.target, "",
                                   "Fichier introuvable")
        bp = await self._backup(p)
        return ExecutionResult(True, "backup_file", a.target,
                               f"Backup cree : {Path(bp).name}", backup_path=bp)

    async def _replace_in_file(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target, must_exist=True)
        if path_error:
            return ExecutionResult(False, "replace_in_file", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "replace_in_file", a.target, "",
                                   "Fichier introuvable")
        if not a.old_str:
            return ExecutionResult(False, "replace_in_file", a.target, "",
                                   "old_str vide - rien a remplacer")
        original = p.read_text("utf-8", errors="replace")
        if a.old_str not in original:
            # Aide au debug : montrer un extrait du fichier
            preview = original[:200]
            return ExecutionResult(False, "replace_in_file", a.target, "",
                                   f"Chaine 'old_str' introuvable dans le fichier. "
                                   f"Debut du fichier : {preview!r:.100}")
        bp = await self._backup(p)
        new_content = original.replace(a.old_str, a.new_str, 1)
        p.write_text(new_content, encoding="utf-8")

        # ── ExecutionGuard : vérification post-remplacement ───────────────────
        try:
            from core.execution_guard import get_guard
            guard_result = await get_guard().guard_replace(
                a.target, a.old_str, a.new_str
            )
            if not guard_result.passed:
                return ExecutionResult(
                    False, "replace_in_file", a.target, "",
                    f"[GUARD FAIL] {guard_result.error}",
                    backup_path=bp,
                )
        except Exception as _guard_err:
            log.warning("execution_guard_error",
                        action="replace_in_file", err=str(_guard_err)[:100])

        return ExecutionResult(True, "replace_in_file", a.target,
                               "Remplacement effectue (1 occurrence)",
                               backup_path=bp)

    async def _run_command(self, a: ActionSpec) -> ExecutionResult:
        cmd = a.command.strip()
        if not cmd:
            return ExecutionResult(False, "run_command", "", "",
                                   "Commande vide")

        # Blacklist absolue
        if _BLACKLIST.search(cmd):
            return ExecutionResult(False, "run_command", cmd, "",
                                   "Commande bloquee par blacklist de securite absolue")

        # Whitelist
        if not _WHITELIST.match(cmd):
            return ExecutionResult(False, "run_command", cmd, "",
                                   f"Commande hors whitelist - non executee. "
                                   f"Commande : '{cmd[:80]}'. "
                                   f"Utilise une commande en lecture seule (ls, cat, grep, python3 script.py...).")
        args, parse_error = _parse_allowed_command(cmd)
        if parse_error:
            return ExecutionResult(False, "run_command", cmd, "", parse_error)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORKSPACE),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=CMD_TIMEOUT
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ExecutionResult(False, "run_command", cmd, "",
                                       f"Timeout apres {CMD_TIMEOUT}s")

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                return ExecutionResult(
                    False, "run_command", cmd,
                    out,
                    f"Exit code {proc.returncode}" + (f" : {err[:200]}" if err else "")
                )
            return ExecutionResult(True, "run_command", cmd, out or "(OK - pas de sortie)")

        except Exception as e:
            return ExecutionResult(False, "run_command", cmd, "", str(e))

    async def _list_dir(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target) if a.target else (WORKSPACE, None)
        if path_error:
            return ExecutionResult(False, "list_dir", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "list_dir", str(p), "",
                                   f"Dossier introuvable : {p}")
        lines = []
        try:
            for item in sorted(p.iterdir()):
                icon = "D" if item.is_dir() else "F"
                size = f"  {item.stat().st_size:,}b" if item.is_file() else ""
                lines.append(f"[{icon}] {item.name}{size}")
        except PermissionError:
            return ExecutionResult(False, "list_dir", str(p), "", "Permission refusee")
        return ExecutionResult(True, "list_dir", str(p),
                               "\n".join(lines) if lines else "(dossier vide)")

    async def _analyze_dir(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target) if a.target else (WORKSPACE, None)
        if path_error:
            return ExecutionResult(False, "analyze_dir", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "analyze_dir", str(p), "",
                                   f"Dossier introuvable : {p}")
        files = [f for f in p.rglob("*") if f.is_file()]
        total = sum(f.stat().st_size for f in files)
        exts: dict[str, int] = {}
        for f in files:
            ext = f.suffix or "(none)"
            exts[ext] = exts.get(ext, 0) + 1
        ext_str = "\n".join(
            f"  {e}: {c}" for e, c in sorted(exts.items(), key=lambda x: -x[1])[:10]
        )
        return ExecutionResult(True, "analyze_dir", str(p),
                               f"Dossier : {p}\n"
                               f"Fichiers : {len(files)} | Total : {total:,} bytes\n\n"
                               f"Extensions :\n{ext_str}")

    async def _delete_file(self, a: ActionSpec) -> ExecutionResult:
        p, path_error = _workspace_path(a.target, must_exist=True)
        if path_error:
            return ExecutionResult(False, "delete_file", a.target, "", path_error)
        if not p.exists():
            return ExecutionResult(False, "delete_file", a.target, "", "Fichier introuvable")
        # Backup systematique avant suppression
        bp = await self._backup(p)
        if p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink()
        return ExecutionResult(True, "delete_file", a.target,
                               f"Supprime. Backup disponible : {Path(bp).name}",
                               backup_path=bp)

    async def _move_file(self, a: ActionSpec) -> ExecutionResult:
        src, src_error = _workspace_path(a.target, must_exist=True)
        if src_error:
            return ExecutionResult(False, "move_file", a.target, "", src_error)
        dst, dst_error = _workspace_path(a.content) if a.content else (None, None)
        if dst_error:
            return ExecutionResult(False, "move_file", a.target, "", dst_error)
        if not src.exists():
            return ExecutionResult(False, "move_file", a.target, "", "Source introuvable")
        if not dst:
            return ExecutionResult(False, "move_file", a.target, "",
                                   "Destination manquante (champ 'content')")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return ExecutionResult(True, "move_file", a.target, f"Deplace vers {dst}")

    async def _copy_file(self, a: ActionSpec) -> ExecutionResult:
        src, src_error = _workspace_path(a.target, must_exist=True)
        if src_error:
            return ExecutionResult(False, "copy_file", a.target, "", src_error)
        dst, dst_error = _workspace_path(a.content) if a.content else (None, None)
        if dst_error:
            return ExecutionResult(False, "copy_file", a.target, "", dst_error)
        if not src.exists():
            return ExecutionResult(False, "copy_file", a.target, "", "Source introuvable")
        if not dst:
            return ExecutionResult(False, "copy_file", a.target, "",
                                   "Destination manquante (champ 'content')")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        return ExecutionResult(True, "copy_file", a.target, f"Copie vers {dst}")

    # ── Utilities ─────────────────────────────────────────────

    async def _backup(self, path: Path) -> str:
        ts   = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        dest = BACKUP_DIR / f"{path.stem}.{ts}{path.suffix}.bak"
        if path.is_dir():
            shutil.copytree(str(path), str(dest))
        else:
            shutil.copy2(str(path), str(dest))
        log.debug("backup_created", src=str(path), dst=str(dest))
        return str(dest)

    async def _log(self, r: ExecutionResult, session_id: str, agent: str, risk: str = "?"):
        entry = {
            "ts":          datetime.now(UTC).isoformat(),
            "session_id":  session_id,
            "agent":       agent,
            "success":     r.success,
            "action":      r.action_type,
            "target":      r.target[:200],
            "duration_ms": r.duration_ms,
            "risk":        risk,
            "error":       r.error,
            "backup":      r.backup_path,
        }
        try:
            with open(EXEC_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.error("exec_log_write_failed", err=str(e))

    async def tail_logs(self, n: int = 15) -> list[dict]:
        if not EXEC_LOG.exists():
            return []
        try:
            lines = EXEC_LOG.read_text("utf-8").strip().splitlines()
            result = []
            for line in lines[-n:]:
                try:
                    result.append(json.loads(line))
                except Exception as _exc:
                    log.warning("swallowed_exception", action="runner_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return result
        except Exception:
            return []


# Backward compatibility alias
# Legacy alias removed — use ActionResult directly or executor.contracts.ExecutionResult
