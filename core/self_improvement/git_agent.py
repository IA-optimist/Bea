"""
core/self_improvement/git_agent.py — Git operations for self-improvement PRs.

Creates a feature branch, applies the patch, commits, pushes, and opens a PR.
Uses subprocess git commands (standard git CLI).

Security:
  - Only creates PRs (no direct merges)
  - Branch name is scoped to "jarvis/si-<run_id>"
  - Commit message includes run_id and score for traceability
  - Never touches protected files (enforced upstream by PromotionPipeline)
"""
from __future__ import annotations

import structlog
import os
import subprocess  # nosec B404
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = structlog.get_logger()


# ── Protected branches (never push directly) ─────────────────────────────────

PROTECTED_BRANCHES = frozenset({"main", "master", "production", "release"})


@dataclass
class CommitInfo:
    """Structured commit information for a self-improvement patch.
    Exported for backward compat (test_devin_core.py imports CommitInfo from here).
    """
    what: str = ""          # What was changed
    why: str = ""           # Why the change was made
    risk: str = "low"       # Risk level: low/medium/high
    files: list[str] = field(default_factory=list)
    patch_id: str = ""

    _RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "⛔"}

    def message(self) -> str:
        emoji = self._RISK_EMOJI.get(self.risk, "🟢")
        header = f"fix(auto): {self.what}"
        parts = [header, "", f"Why: {self.why}", f"Risk: {emoji} {self.risk}"]
        if self.patch_id:
            parts.append(f"Patch-ID: {self.patch_id}")
        if self.files:
            parts.append(f"Files: {', '.join(self.files)}")
        return "\n".join(parts)


@dataclass
class PRInfo:
    """Pull request information for a self-improvement patch."""
    branch: str = ""
    title: str = ""
    body: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)




# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class WorkspaceSnapshot:
    """Snapshot of workspace state before patching."""
    base_commit: str = ""
    base_branch: str = "main"
    sandbox_branch: str = ""
    sandbox_path: str = ""
    method: str = "tempcopy"
    active: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommitSuggestion:
    """Structured commit message for a self-improvement patch."""
    title: str = ""
    body: str = ""
    risk: str = "low"
    patch_id: str = ""
    files: list[str] = field(default_factory=list)

    _RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "⛔"}

    def message(self) -> str:
        emoji = self._RISK_EMOJI.get(self.risk, "🟢")
        header = f"fix(auto): {self.title}"
        parts = [header, "", self.body, "", f"Risk: {emoji} {self.risk}"]
        if self.patch_id:
            parts.append(f"Patch-ID: {self.patch_id}")
        if self.files:
            parts.append(f"Files: {', '.join(self.files)}")
        return "\n".join(parts)


@dataclass
class PatchResult:
    """Result of applying a patch to the workspace."""
    applied: bool = False
    changed_files: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    error: str = ""
    rollback_command: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Config ────────────────────────────────────────────────────────────────────

GITHUB_REPO = os.getenv("GITHUB_REPO", "")          # e.g. "owner/repo"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")        # Personal access token
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "JarvisMax-SI")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "jarvis-si@noreply.jarvismax.ai")
BASE_BRANCH = os.getenv("SI_BASE_BRANCH", "master")


def _run_git(args: list[str], cwd: Path, env: Optional[dict] = None) -> tuple[int, str]:
    """Run a git command. Returns (returncode, combined output)."""
    git_env = os.environ.copy()
    if GITHUB_TOKEN:
        git_env["GIT_ASKPASS"] = ""
        git_env["GIT_TERMINAL_PROMPT"] = "0"
    if env:
        git_env.update(env)

    try:
        result = subprocess.run(  # nosec B603 B607
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            env=git_env,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "git command timed out"
    except Exception as exc:
        return 1, str(exc)


def _apply_diff_to_files(unified_diff: str, project_root: Path) -> tuple[bool, str]:
    """Apply unified diff to project files. Returns (success, error)."""
    if not unified_diff.strip():
        return True, ""

    diff_file = project_root / ".si_patch.diff"
    try:
        diff_file.write_text(unified_diff, encoding="utf-8")
        rc, out = _run_git(["apply", "--check", str(diff_file)], cwd=project_root)
        if rc != 0:
            diff_file.unlink(missing_ok=True)
            return False, f"git apply --check failed: {out}"

        rc, out = _run_git(["apply", str(diff_file)], cwd=project_root)
        diff_file.unlink(missing_ok=True)
        if rc != 0:
            return False, f"git apply failed: {out}"
        return True, ""
    except Exception as exc:
        diff_file.unlink(missing_ok=True)
        return False, str(exc)


class GitAgent:
    """
    Creates a git branch, applies a patch, and opens a PR.

    Requires:
      - GITHUB_REPO env var: "owner/repo"
      - GITHUB_TOKEN env var: personal access token with repo:write
      - Project must be a git repository
    """

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root

    def has_worktree_support(self) -> bool:
        """Check if the project is a git repo with worktree support."""
        try:
            rc, out = _run_git(["rev-parse", "--is-inside-work-tree"], self.project_root)
            if rc != 0:
                return False
            rc, out = _run_git(["worktree", "list"], self.project_root)
            return rc == 0
        except Exception:
            return False

    def create_sandbox(self, patch_id: str) -> WorkspaceSnapshot:
        """Create a sandbox workspace for the given patch_id.
        
        Uses git worktree if available, otherwise falls back to tempcopy.
        """
        snapshot = WorkspaceSnapshot(sandbox_branch=f"auto/{patch_id}")
        if self.has_worktree_support():
            try:
                return self._create_worktree(snapshot, patch_id)
            except Exception as _exc:
                log.warning("swallowed_exception", action="git_agent_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return self._create_tempcopy(snapshot)

    def _create_worktree(self, snapshot: WorkspaceSnapshot, patch_id: str) -> WorkspaceSnapshot:
        """Create a git worktree sandbox."""
        import tempfile as _tf
        tmp = _tf.mkdtemp(prefix=f"jarvis-wt-{patch_id}-")
        branch = f"jarvis/sandbox-{patch_id}-{int(time.time())}"
        rc, out = _run_git(["worktree", "add", "-b", branch, tmp], self.project_root)
        if rc != 0:
            raise RuntimeError(f"git worktree add failed: {out}")
        snapshot.sandbox_path = tmp
        snapshot.sandbox_branch = branch
        snapshot.method = "worktree"
        snapshot.active = True
        try:
            rc2, commit = _run_git(["rev-parse", "HEAD"], self.project_root)
            if rc2 == 0:
                snapshot.base_commit = commit.strip()
        except Exception as _exc:
            log.warning("swallowed_exception", action="git_agent_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return snapshot

    def get_rollback_command(self, snapshot: WorkspaceSnapshot) -> str:
        """Return a rollback command string for a sandbox snapshot."""
        if snapshot.method == "tempcopy":
            return f"rm -rf {snapshot.sandbox_path}"
        elif snapshot.method == "worktree":
            return f"git worktree remove {snapshot.sandbox_path} && git branch -D {snapshot.sandbox_branch}"
        return ""

    def suggest_pr(
        self,
        patch_id: str,
        title: str,
        diff: str,
        test_summary: str,
    ) -> dict:
        """Generate a PR suggestion dict (title + body) without pushing."""
        body_parts = [
            f"## {title}",
            "",
            "### Diff",
            f"```diff\n{diff}\n```",
            "",
            "### Test Results",
            test_summary,
            "",
            f"Patch-ID: `{patch_id}`",
        ]
        return {"title": f"[SI] {title}", "body": "\n".join(body_parts)}

    def _create_tempcopy(self, snapshot: WorkspaceSnapshot) -> WorkspaceSnapshot:
        """Create a temporary copy of the workspace for sandboxed patching."""
        import shutil
        tmp = tempfile.mkdtemp(prefix="jarvis-si-")
        shutil.copytree(str(self.project_root), tmp, dirs_exist_ok=True)
        snapshot.sandbox_path = tmp
        snapshot.method = "tempcopy"
        snapshot.active = True
        # Get base commit if in a git repo
        try:
            rc, out = _run_git(["rev-parse", "HEAD"], self.project_root)
            if rc == 0:
                snapshot.base_commit = out.strip()
        except Exception as _exc:
            log.warning("swallowed_exception", action="git_agent_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return snapshot

    def _diff_tempcopy(self, snapshot: WorkspaceSnapshot, patch_result: PatchResult) -> PatchResult:
        """Compare sandbox copy to original and populate PatchResult with changes."""
        if not snapshot.sandbox_path or not os.path.exists(snapshot.sandbox_path):
            patch_result.error = "Sandbox path missing"
            return patch_result
        try:
            # Walk the sandbox and compare to original
            changed = []
            total_added = 0
            total_removed = 0
            sandbox = Path(snapshot.sandbox_path)
            for root, dirs, files in os.walk(sandbox):
                for fname in files:
                    sandbox_file = Path(root) / fname
                    rel = sandbox_file.relative_to(sandbox)
                    orig_file = self.project_root / rel
                    if not orig_file.exists():
                        changed.append(rel.as_posix())  # chemins repo en '/' (cross-plateforme)
                        try:
                            total_added += len(sandbox_file.read_text(encoding="utf-8").splitlines())
                        except Exception:
                            total_added += 1
                    elif sandbox_file.read_bytes() != orig_file.read_bytes():
                        changed.append(rel.as_posix())  # chemins repo en '/' (cross-plateforme)
                        try:
                            orig_lines = orig_file.read_text(encoding="utf-8").splitlines()
                            new_lines = sandbox_file.read_text(encoding="utf-8").splitlines()
                            # Count differing lines
                            import difflib
                            diff = list(difflib.unified_diff(orig_lines, new_lines, lineterm=""))
                            for line in diff:
                                if line.startswith("+") and not line.startswith("+++"):
                                    total_added += 1
                                elif line.startswith("-") and not line.startswith("---"):
                                    total_removed += 1
                        except Exception:
                            total_added += 1
                            total_removed += 1
            if changed:
                patch_result.applied = True
                patch_result.changed_files = changed
                patch_result.lines_added = total_added
                patch_result.lines_removed = total_removed
                patch_result.rollback_command = f"rm -rf {snapshot.sandbox_path}"
            return patch_result
        except Exception as exc:
            patch_result.error = str(exc)
            return patch_result

    def cleanup_sandbox(self, snapshot: WorkspaceSnapshot) -> None:
        """Remove the sandbox temporary directory (tempcopy or worktree)."""
        try:
            if snapshot.method == "worktree":
                _run_git(["worktree", "remove", "--force", snapshot.sandbox_path], self.project_root)
                if snapshot.sandbox_branch:
                    _run_git(["branch", "-D", snapshot.sandbox_branch], self.project_root)
            else:
                import shutil
                if snapshot.sandbox_path and os.path.exists(snapshot.sandbox_path):
                    shutil.rmtree(snapshot.sandbox_path)
            snapshot.active = False
        except Exception:
            # Fallback: try rmtree anyway
            try:
                import shutil
                if snapshot.sandbox_path and os.path.exists(snapshot.sandbox_path):
                    shutil.rmtree(snapshot.sandbox_path)
            except Exception as _exc:
                log.warning("swallowed_exception", action="git_agent_4", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            snapshot.active = False

    def _get_tempcopy_diff(self, snapshot: WorkspaceSnapshot) -> str:
        """Get the diff between the original workspace and the sandbox copy."""
        if not snapshot.sandbox_path or not os.path.exists(snapshot.sandbox_path):
            return ""
        try:
            result = subprocess.run(  # nosec B603 B607
                ["diff", "-ruN", str(self.project_root), snapshot.sandbox_path],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout
        except Exception:
            return ""

    def create_improvement_pr(
        self,
        unified_diff: str,
        changed_files: list[str],
        domain: str,
        run_id: str,
        explanation: str,
        score: float,
    ) -> str:
        """
        Create a PR for a validated improvement.

        Returns PR URL string on success, "" on failure.
        Never raises.
        """
        if not GITHUB_REPO:
            log.warning("git_agent.no_github_repo — set GITHUB_REPO env var")
            return ""

        if not GITHUB_TOKEN:
            log.warning("git_agent.no_github_token — set GITHUB_TOKEN env var")
            return ""

        branch_name = f"jarvis/si-{run_id}"

        try:
            return self._create_pr_flow(
                unified_diff=unified_diff,
                changed_files=changed_files,
                domain=domain,
                run_id=run_id,
                branch_name=branch_name,
                explanation=explanation,
                score=score,
            )
        except Exception as exc:
            log.error("git_agent.unexpected_error", run_id=run_id, err=str(exc))
            return ""

    def _create_pr_flow(
        self,
        unified_diff: str,
        changed_files: list[str],
        domain: str,
        run_id: str,
        branch_name: str,
        explanation: str,
        score: float,
    ) -> str:
        root = self.project_root

        # Ensure we're on a clean state
        rc, out = _run_git(["status", "--porcelain"], cwd=root)
        if rc != 0:
            log.warning("git_agent.git_status_failed", out=out)
            return ""

        # Stash any working changes to avoid conflicts
        has_changes = bool(out.strip())
        if has_changes:
            _run_git(["stash", "push", "-m", f"jarvis-si-stash-{run_id}"], cwd=root)

        try:
            return self._do_branch_and_pr(
                unified_diff, changed_files, domain, run_id,
                branch_name, explanation, score, root,
            )
        finally:
            # Restore stashed changes if any
            if has_changes:
                _run_git(["stash", "pop"], cwd=root)

    def _do_branch_and_pr(
        self,
        unified_diff: str,
        changed_files: list[str],
        domain: str,
        run_id: str,
        branch_name: str,
        explanation: str,
        score: float,
        root: Path,
    ) -> str:
        # Fetch latest base branch
        _run_git(["fetch", "origin", BASE_BRANCH], cwd=root)

        # Create new branch from base
        rc, out = _run_git(
            ["checkout", "-b", branch_name, f"origin/{BASE_BRANCH}"],
            cwd=root,
        )
        if rc != 0:
            # Branch might already exist
            rc, out = _run_git(["checkout", branch_name], cwd=root)
            if rc != 0:
                log.error("git_agent.branch_failed", branch=branch_name, out=out)
                return ""

        # Apply the diff
        applied, err = _apply_diff_to_files(unified_diff, root)
        if not applied:
            log.error("git_agent.apply_failed", err=err)
            _run_git(["checkout", BASE_BRANCH], cwd=root)
            _run_git(["branch", "-D", branch_name], cwd=root)
            return ""

        # Configure git user
        _run_git(["config", "user.name", GIT_USER_NAME], cwd=root)
        _run_git(["config", "user.email", GIT_USER_EMAIL], cwd=root)

        # Stage changed files
        for f in changed_files:
            _run_git(["add", f], cwd=root)

        # Commit
        commit_msg = (
            f"feat(si): [{domain}] self-improvement patch {run_id}\n\n"
            f"Score: {score:.2f}\n"
            f"Changed: {', '.join(changed_files[:5])}\n\n"
            f"{explanation[:500]}\n\n"
            f"Generated by JarvisMax Self-Improvement V3\n"
            f"Run ID: {run_id}\n"
            f"Auto-applied: NO — requires human review via PR"
        )

        rc, out = _run_git(
            ["commit", "-m", commit_msg],
            cwd=root,
        )
        if rc != 0 and "nothing to commit" not in out:
            log.error("git_agent.commit_failed", out=out)
            _run_git(["checkout", BASE_BRANCH], cwd=root)
            _run_git(["branch", "-D", branch_name], cwd=root)
            return ""

        # Push branch
        remote_url = self._build_remote_url()
        rc, out = _run_git(
            ["push", remote_url, f"HEAD:{branch_name}", "--force-with-lease"],
            cwd=root,
        )
        if rc != 0:
            # Retry with regular push
            rc, out = _run_git(
                ["push", remote_url, f"HEAD:{branch_name}"],
                cwd=root,
            )
            if rc != 0:
                log.error("git_agent.push_failed", out=out[:300])
                _run_git(["checkout", BASE_BRANCH], cwd=root)
                return ""

        # Return to base branch
        _run_git(["checkout", BASE_BRANCH], cwd=root)

        # Create PR via GitHub API
        pr_url = self._create_github_pr(
            branch_name=branch_name,
            domain=domain,
            run_id=run_id,
            explanation=explanation,
            score=score,
            changed_files=changed_files,
        )

        return pr_url

    def _build_remote_url(self) -> str:
        """Build authenticated remote URL."""
        if GITHUB_TOKEN:
            return f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        return f"https://github.com/{GITHUB_REPO}.git"

    def _create_github_pr(
        self,
        branch_name: str,
        domain: str,
        run_id: str,
        explanation: str,
        score: float,
        changed_files: list[str],
    ) -> str:
        """Create PR via GitHub REST API. Returns PR URL."""
        try:
            import json
            import urllib.request
            import urllib.error

            owner, repo = GITHUB_REPO.split("/", 1)
            api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"

            title = f"[JarvisMax SI] {domain}: self-improvement patch {run_id} (score={score:.2f})"
            body = (
                f"## Self-Improvement Patch\n\n"
                f"**Run ID:** `{run_id}`  \n"
                f"**Domain:** {domain}  \n"
                f"**Score:** {score:.2f}/1.00  \n"
                f"**Changed files:** {', '.join(f'`{f}`' for f in changed_files[:5])}  \n\n"
                f"### Explanation\n{explanation[:1000]}\n\n"
                f"### Review Required\n"
                f"This PR was generated by JarvisMax Self-Improvement V3.  \n"
                f"It was validated in a Docker sandbox (--network=none).  \n"
                f"**Manual review required before merging.**\n\n"
                f"---\n"
                f"*Generated by JarvisMax SI | Auto-merge: DISABLED*"
            )

            payload = json.dumps({
                "title": title,
                "head": branch_name,
                "base": BASE_BRANCH,
                "body": body,
                "draft": False,
            }).encode("utf-8")

            req = urllib.request.Request(
                api_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                data = json.loads(resp.read().decode("utf-8"))
                pr_url = data.get("html_url", "")
                log.info("git_agent.pr_created", pr_url=pr_url, run_id=run_id)
                return pr_url

        except Exception as exc:
            log.error("git_agent.github_api_failed", err=str(exc)[:200])
            return f"branch:{branch_name}"  # Return branch name as fallback


# ── Singleton ──────────────────────────────────────────────────────────────────

_agent: GitAgent | None = None


def get_git_agent() -> GitAgent:
    global _agent
    if _agent is None:
        _agent = GitAgent()
    return _agent
