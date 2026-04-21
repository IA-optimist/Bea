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
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(os.environ.get("JARVIS_ROOT", "/app"))
_WORKSPACE  = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_MAX_LINES_PER_FILE = 150  # max lines of context fed to LLM per file


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

    # ── 4. Backup + apply ─────────────────────────────────────────
    backups: dict[str, str] = {}
    applied_changes = []

    try:
        for file_path, find_text, replace_text in patch_blocks:
            full_path = _REPO_ROOT / file_path
            if not full_path.exists():
                continue

            original = full_path.read_text("utf-8")
            if find_text not in original:
                log.warning("proposal_apply_find_not_found",
                            proposal_id=proposal_id, file=file_path, find=find_text[:60])
                continue

            backups[file_path] = original
            modified = original.replace(find_text, replace_text, 1)

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

    # ── 5. Run tests ──────────────────────────────────────────────
    try:
        from core.tools.repo_inspector import run_tests
        test_result = run_tests("tests/", timeout=90)
        result.tests_passed = bool(test_result.get("ok"))
        result.tests_output = test_result.get("output", "")[:500]
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

    try:
        factory = LLMFactory(get_settings())
        resp = await factory.safe_invoke(
            [SystemMessage(content=system), HumanMessage(content=user)],
            role="director",
            timeout=60.0,
        )
        raw = getattr(resp, "content", "") or ""
        return _parse_patch_blocks(raw, files_to_modify)
    except Exception as e:
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
    current = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(_REPO_ROOT), text=True
    ).strip()

    if current in ("main", "master", "production"):
        # Create SI branch off current
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(_REPO_ROOT), check=True, capture_output=True
        )

    # Stage changed files
    for f in changed_files:
        subprocess.run(
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
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(_REPO_ROOT), check=True, capture_output=True
    )
    log.info("proposal_committed", branch=branch, files=changed_files)
