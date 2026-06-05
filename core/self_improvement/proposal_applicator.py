"""
core/self_improvement/proposal_applicator.py — Apply improvement proposals safely.

Pipeline:
  1. Load proposal by ID
  2. Use LLM to generate minimal FIND→REPLACE patch from fix_proposed + file context
  3. Backup affected files
  4. Apply patch (with syntax validation)
  5. Run tests
  6. If tests pass → commit to jarvis/si-<id> branch, mark proposal "applied"
  7. If tests fail → restore backups, mark proposal "failed", return error
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess  # nosec B404
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# Racine du repo : JARVIS_ROOT si défini (Docker=/app), sinon résolue depuis ce module
# (core/self_improvement/proposal_applicator.py -> remonte de 2 niveaux). Sans ça, le
# défaut "/app" rendait introuvables tous les fichiers en local (hors Docker).
_REPO_ROOT = Path(os.environ.get("JARVIS_ROOT") or Path(__file__).resolve().parents[2])
_WORKSPACE  = Path(os.environ.get("WORKSPACE_DIR") or (_REPO_ROOT / "workspace"))
_MAX_LINES_PER_FILE = 400  # max lines de contexte par fichier (150 coupait le code cible)


@dataclass
class ApplyResult:
    proposal_id: str
    ok: bool
    committed: bool = False
    branch: str = ""
    tests_passed: bool = False
    tests_output: str = ""
    changes: list[dict] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "ok": self.ok,
            "committed": self.committed,
            "branch": self.branch,
            "tests_passed": self.tests_passed,
            "tests_output": self.tests_output[:500],
            "changes": self.changes,
            "error": self.error[:300],
        }


def _failed_tests(output: str) -> set[str]:
    """Extrait les identifiants de tests FAILED d'une sortie pytest."""
    return set(re.findall(r"^FAILED (\S+)", output or "", re.M)) | \
        set(re.findall(r"(\S+::\S+)\s+FAILED", output or ""))


def _tolerant_find_replace(original: str, find: str, replace: str) -> tuple[str, bool]:
    """Applique find->replace. Exact d'abord, sinon match ligne-à-ligne en ignorant
    l'indentation/whitespace de bord (le défaut le plus fréquent des FIND générés par LLM)."""
    if find and find in original:
        return original.replace(find, replace, 1), True
    o_lines = original.split("\n")
    f_lines = [ln for ln in find.strip("\n").split("\n")]
    fs = [ln.strip() for ln in f_lines]
    if not any(fs):
        return original, False
    n = len(f_lines)

    def _indent(s: str) -> str:
        return s[:len(s) - len(s.lstrip())]
    for i in range(len(o_lines) - n + 1):
        if all(o_lines[i + j].strip() == fs[j] for j in range(n)):
            r_lines = replace.strip("\n").split("\n")
            # Ré-indenter le remplacement sur l'indentation du bloc original (le LLM
            # donne parfois un replace mal/non-indenté -> SyntaxError sinon).
            orig_ind = _indent(o_lines[i])
            repl_ind = _indent(next((ln for ln in r_lines if ln.strip()), ""))
            reind = [(orig_ind + ln[len(repl_ind):]) if ln.strip() else ""
                     for ln in r_lines]
            return "\n".join(o_lines[:i] + reind + o_lines[i + n:]), True
    return original, False


def _test_pattern(file_paths: list[str]) -> str:
    """Construit un motif pytest -k ciblé à partir des fichiers modifiés."""
    toks: set[str] = set()
    for fp in file_paths:
        toks.add(Path(fp).stem)
        toks.add(Path(fp).parent.name)
    return " or ".join(sorted(
        t for t in toks if len(t) > 3 and t not in ("core", "api", "src", "self", "test")))


async def apply_proposal(proposal_id: str) -> ApplyResult:
    """
    Full apply pipeline for an ImprovementProposal.
    Returns ApplyResult — always safe to call (fail-open on errors).
    """
    result = ApplyResult(proposal_id=proposal_id, ok=False)

    # ── 1. Load proposal ─────────────────────────────────────────
    proposal = _load_proposal(proposal_id)
    if proposal is None:
        result.error = f"Proposal '{proposal_id}' not found"
        return result

    if proposal.get("status") in ("applied", "rejected"):
        result.error = f"Proposal already {proposal['status']}"
        return result

    files_to_modify = proposal.get("files_to_modify", [])
    fix_proposed    = proposal.get("fix_proposed", "")
    if not files_to_modify or not fix_proposed:
        result.error = "Proposal has no files_to_modify or fix_proposed"
        return result

    # ── 2. Read file context ──────────────────────────────────────
    file_contexts = []
    for fpath in files_to_modify[:3]:
        full_path = _REPO_ROOT / fpath
        if full_path.exists():
            lines = full_path.read_text("utf-8").splitlines()[:_MAX_LINES_PER_FILE]
            file_contexts.append(f"### {fpath}\n```python\n" + "\n".join(lines) + "\n```")

    if not file_contexts:
        result.error = "None of the files_to_modify were found on disk"
        return result

    # ── 3. Use LLM to generate the patch ─────────────────────────
    patch_blocks = await _generate_patch_via_llm(fix_proposed, file_contexts, files_to_modify)
    if not patch_blocks:
        result.error = "LLM returned no valid FIND/REPLACE blocks"
        return result

    # ── 3b. Baseline tests AVANT patch (delta-gate) ───────────────
    # On enregistre les tests ciblés déjà en échec sur le code ORIGINAL, pour ne
    # rejeter ensuite que les NOUVEAUX échecs introduits par le patch (sinon un test
    # flaky/pré-existant bloquerait toute amélioration valide).
    from core.tools.repo_inspector import run_tests
    _pattern = _test_pattern(files_to_modify)
    try:
        _baseline_failed = _failed_tests(run_tests("tests/", pattern=_pattern, timeout=115).get("output", ""))
    except Exception:  # noqa: BLE001
        _baseline_failed = set()

    # ── 4. Backup + apply ─────────────────────────────────────────
    backups: dict[str, str] = {}
    applied_changes = []

    try:
        for file_path, find_text, replace_text in patch_blocks:
            full_path = _REPO_ROOT / file_path
            if not full_path.exists():
                continue

            original = full_path.read_text("utf-8")
            modified, _matched = _tolerant_find_replace(original, find_text, replace_text)
            if not _matched:
                log.warning("proposal_apply_find_not_found",
                            proposal_id=proposal_id, file=file_path, find=find_text[:60])
                continue

            # Sauvegarde le VRAI original une seule fois (plusieurs blocs sur le même
            # fichier ré-écraseraient le backup avec un état déjà patché -> rollback partiel).
            backups.setdefault(file_path, original)

            # Syntax check (Python only)
            if file_path.endswith(".py"):
                try:
                    ast.parse(modified)
                except SyntaxError as e:
                    result.error = f"Syntax error in {file_path} after patch: {e}"
                    _restore_backups(backups)
                    return result

            from core.self_improvement.protected_paths import is_protected
            if is_protected(file_path):
                result.error = f"File {file_path} is protected"
                _restore_backups(backups)
                return result

            full_path.write_text(modified, "utf-8")
            applied_changes.append({
                "file": file_path,
                "find_preview": find_text[:80],
                "replace_preview": replace_text[:80],
            })
            log.info("proposal_patch_applied",
                     proposal_id=proposal_id, file=file_path)

    except Exception as e:
        result.error = f"Apply error: {str(e)[:200]}"
        _restore_backups(backups)
        return result

    if not applied_changes:
        result.error = "No changes were applied (find text not found in any file)"
        return result

    result.changes = applied_changes

    # ── 5. Run tests (DELTA-GATE : seuls les NOUVEAUX échecs rejettent) ──
    try:
        _after = run_tests("tests/", pattern=_pattern, timeout=115)
        _out = _after.get("output", "")
        _after_failed = _failed_tests(_out)
        _new_failures = _after_failed - _baseline_failed
        # OK si le patch n'introduit AUCUN nouvel échec (les pré-existants sont tolérés).
        result.tests_passed = not _new_failures
        result.tests_output = (
            f"nouveaux échecs introduits: {sorted(_new_failures)}" if _new_failures
            else f"OK — 0 nouvel échec (baseline pré-existante: {len(_baseline_failed)})")[:500]
    except Exception as e:
        result.tests_passed = False
        result.tests_output = f"Test runner error: {str(e)[:100]}"

    if not result.tests_passed:
        log.warning("proposal_tests_failed_rollback",
                    proposal_id=proposal_id, output=result.tests_output[:100])
        _restore_backups(backups)
        _mark_proposal_status(proposal_id, "test_failed")
        result.error = "Tests failed — changes rolled back"
        return result

    # ── 6. Commit ─────────────────────────────────────────────────
    branch = f"jarvis/si-{proposal_id[:8]}"
    try:
        _git_commit(branch, proposal, applied_changes)
        result.committed = True
        result.branch = branch
    except Exception as e:
        log.warning("proposal_commit_failed", err=str(e)[:100])
        result.committed = False  # Changes are still on disk — just not committed

    _mark_proposal_status(proposal_id, "applied")
    result.ok = True
    log.info("proposal_applied_successfully",
             proposal_id=proposal_id, committed=result.committed, branch=branch)
    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _generate_patch_via_llm(
    fix_proposed: str,
    file_contexts: list[str],
    files_to_modify: list[str],
) -> list[tuple[str, str, str]]:
    """
    Ask LLM to produce FIND/REPLACE blocks for the proposed fix.
    Returns list of (file_path, find_text, replace_text).
    """
    from config.settings import get_settings
    from core.llm_factory import LLMFactory
    from langchain_core.messages import SystemMessage, HumanMessage

    system = """You are a precise code editor for the JarvisMax project.
Given a problem description and relevant file contents, produce the minimal code change.

Respond ONLY with blocks in this exact format:
FILE: path/to/file.py
FIND:
<exact text to find>
REPLACE:
<replacement text>
---

Rules:
- One block per file changed
- FIND must match exactly (including indentation)
- Keep changes minimal — 1 to 10 lines max
- Do not add unrelated changes
- Do not change function signatures unless explicitly required"""

    user = f"""Problem to fix: {fix_proposed}

Files:
{chr(10).join(file_contexts)}

Files that may be modified: {', '.join(files_to_modify[:3])}

Generate the minimal FIND/REPLACE block(s) to fix the problem."""

    msgs = [SystemMessage(content=system), HumanMessage(content=user)]
    import os as _os
    _or_key = _os.getenv("OPENROUTER_API_KEY", "")
    # Le LLM génère parfois un FIND qui ne matche pas exactement (non-déterminisme).
    # On retente jusqu'à 3 fois et on ne garde que les blocs dont le FIND existe VRAIMENT.
    for attempt in range(3):
        try:
            if _or_key:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model=_os.getenv("AGENT_OR_MODEL", "openai/gpt-oss-120b:free"),
                    base_url="https://openrouter.ai/api/v1", api_key=_or_key,
                    temperature=0.0 if attempt == 0 else 0.4, timeout=90, max_retries=2)
                resp = await llm.ainvoke(msgs)
            else:
                factory = LLMFactory(get_settings())
                resp = await factory.safe_invoke(msgs, role="director", timeout=60.0)
            blocks = _parse_patch_blocks(getattr(resp, "content", "") or "", files_to_modify)
            valid = []
            for fp, find, repl in blocks:
                full = _REPO_ROOT / fp
                if find and full.exists() and _tolerant_find_replace(
                        full.read_text("utf-8"), find, repl)[1]:
                    valid.append((fp, find, repl))
            if valid:
                return valid
            log.info("patch_find_mismatch_retry", attempt=attempt, blocks=len(blocks))
        except Exception as e:  # noqa: BLE001
            log.warning("patch_llm_failed", err=str(e)[:80])
    return []


def _parse_patch_blocks(
    raw: str,
    allowed_files: list[str],
) -> list[tuple[str, str, str]]:
    """Parse LLM output into (file_path, find_text, replace_text) tuples."""
    results = []
    blocks = raw.split("---")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            file_line = ""
            find_text = ""
            replace_text = ""
            state = None

            for line in block.splitlines():
                if line.startswith("FILE:"):
                    file_line = line[5:].strip()
                    state = None
                elif line.strip() == "FIND:":
                    state = "find"
                elif line.strip() == "REPLACE:":
                    state = "replace"
                else:
                    if state == "find":
                        find_text += line + "\n"
                    elif state == "replace":
                        replace_text += line + "\n"

            # Strip trailing newlines
            find_text    = find_text.rstrip("\n")
            replace_text = replace_text.rstrip("\n")

            if file_line and find_text and file_line in allowed_files:
                results.append((file_line, find_text, replace_text))
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
            continue

    return results


def _restore_backups(backups: dict[str, str]) -> None:
    for file_path, original in backups.items():
        try:
            (_REPO_ROOT / file_path).write_text(original, "utf-8")
            log.info("proposal_backup_restored", file=file_path)
        except Exception as e:
            log.error("proposal_restore_failed", file=file_path, err=str(e)[:60])


def _load_proposal(proposal_id: str) -> Optional[dict]:
    proposals_path = _WORKSPACE / "improvement_proposals.json"
    try:
        if not proposals_path.exists():
            return None
        data = json.loads(proposals_path.read_text("utf-8"))
        items = data if isinstance(data, list) else []
        for item in items:
            if item.get("proposal_id") == proposal_id:
                return item
        return None
    except Exception:
        return None


def _mark_proposal_status(proposal_id: str, status: str) -> None:
    proposals_path = _WORKSPACE / "improvement_proposals.json"
    try:
        if not proposals_path.exists():
            return
        data = json.loads(proposals_path.read_text("utf-8"))
        items = data if isinstance(data, list) else []
        for item in items:
            if item.get("proposal_id") == proposal_id:
                item["status"] = status
                item["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                break
        proposals_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        log.warning("mark_proposal_status_failed", err=str(e)[:60])


def _git_commit(branch: str, proposal: dict, changes: list[dict]) -> None:
    """Create branch, stage changes, commit."""

    changed_files = [c["file"] for c in changes]

    # Never push to protected branches
    current = subprocess.check_output(  # nosec B603 B607
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(_REPO_ROOT), text=True
    ).strip()

    if current in ("main", "master", "production"):
        # Create SI branch off current
        subprocess.run(  # nosec B603 B607
            ["git", "checkout", "-b", branch],
            cwd=str(_REPO_ROOT), check=True, capture_output=True
        )

    # Stage changed files
    for f in changed_files:
        subprocess.run(  # nosec B603 B607
            ["git", "add", f],
            cwd=str(_REPO_ROOT), check=True, capture_output=True
        )

    msg = (
        f"self-improvement: apply proposal {proposal.get('proposal_id', '')[:8]}\n\n"
        f"Problem: {proposal.get('problem', '')[:120]}\n"
        f"Fix: {proposal.get('fix_proposed', '')[:200]}\n"
        f"Risk: {proposal.get('risk_level', 'low')}\n"
        f"Files: {', '.join(changed_files)}"
    )
    subprocess.run(  # nosec B603 B607
        ["git", "commit", "-m", msg],
        cwd=str(_REPO_ROOT), check=True, capture_output=True
    )
    log.info("proposal_committed", branch=branch, files=changed_files)
