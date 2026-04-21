"""
connectors/github_connector.py — GitHub integration via gh CLI.

Actions:
  create_repo: Create a new repository
  commit_files: Commit and push files to a repo
  create_issue: Create an issue
"""
from __future__ import annotations

import subprocess
from .base import ConnectorBase, ConnectorResult


class GitHubConnector(ConnectorBase):
    name = "github"
    description = "GitHub repository management via gh CLI"
    actions = ["create_repo", "commit_files", "create_issue"]

    def is_configured(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        try:
            r = subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def execute(self, action: str, params: dict) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)

        if action == "create_repo":
            return self._create_repo(params, result)
        elif action == "commit_files":
            return self._commit_files(params, result)
        elif action == "create_issue":
            return self._create_issue(params, result)
        else:
            result.error = f"Unknown action: {action}"
            return result

    def _create_repo(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        name = params.get("name", "")
        private = params.get("private", True)
        description = params.get("description", "")

        if not name:
            result.error = "repo name required"
            return result

        cmd = ["gh", "repo", "create", name]
        if private:
            cmd.append("--private")
        else:
            cmd.append("--public")
        if description:
            cmd.extend(["--description", description])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            result.success = r.returncode == 0
            result.output = {"stdout": r.stdout[:500], "stderr": r.stderr[:200]}
            if not result.success:
                result.error = r.stderr[:200]
        except Exception as e:
            result.error = str(e)[:200]

        return result

    def _commit_files(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        repo_dir = params.get("repo_dir", "")
        message = params.get("message", "Update from Jarvis")
        files = params.get("files", [])

        if not repo_dir:
            result.error = "repo_dir required"
            return result

        try:
            # Stage files
            if files:
                for f in files:
                    subprocess.run(["git", "add", f], cwd=repo_dir, capture_output=True, timeout=10)
            else:
                subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True, timeout=10)

            # Commit
            r = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )
            result.output["commit"] = r.stdout[:300]

            # Push
            r2 = subprocess.run(
                ["git", "push"],
                cwd=repo_dir, capture_output=True, text=True, timeout=60,
            )
            result.success = r2.returncode == 0
            result.output["push"] = r2.stdout[:200]
            if not result.success:
                result.error = r2.stderr[:200]
        except Exception as e:
            result.error = str(e)[:200]

        return result

    def _create_issue(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        repo = params.get("repo", "")
        title = params.get("title", "")
        body = params.get("body", "")

        if not repo or not title:
            result.error = "repo and title required"
            return result

        cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
        if body:
            cmd.extend(["--body", body])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            result.success = r.returncode == 0
            result.output = {"stdout": r.stdout[:500]}
            if not result.success:
                result.error = r.stderr[:200]
        except Exception as e:
            result.error = str(e)[:200]

        return result
