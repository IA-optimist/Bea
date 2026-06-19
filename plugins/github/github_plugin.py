"""
plugins/github/github_plugin.py — GitHub Integration Plugin

Provides GitHub repository management, issue tracking, and PR operations
as a Bea plugin with manifest-based permissions.
"""
from typing import Any, Dict, Optional
import structlog

from plugins.plugin_models import PluginMetadata
from plugins.plugin_registry import get_plugin_registry

log = structlog.get_logger("plugins.github")


class GitHubPlugin:
    """GitHub integration plugin for Bea."""
    
    metadata = PluginMetadata(
        plugin_id="github",
        name="GitHub Integration",
        version="1.0.0",
        description="GitHub repository management, issues, and PR operations",
        author="Bea Team",
        risk_level="medium",
        required_secrets=["GITHUB_PERSONAL_ACCESS_TOKEN"],
        required_configs=["GITHUB_DEFAULT_OWNER"],
    )
    
    def __init__(self):
        self._token: Optional[str] = None
        self._default_owner: Optional[str] = None
    
    async def invoke(self, action: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a GitHub action.
        
        Actions:
        - create_repo: Create a new repository
        - list_repos: List repositories for an owner
        - create_issue: Create an issue
        - create_pr: Create a pull request
        - get_file: Get file content from repository
        - update_file: Update file in repository
        """
        try:
            if action == "create_repo":
                return await self._create_repo(params, context)
            elif action == "list_repos":
                return await self._list_repos(params, context)
            elif action == "create_issue":
                return await self._create_issue(params, context)
            elif action == "create_pr":
                return await self._create_pr(params, context)
            elif action == "get_file":
                return await self._get_file(params, context)
            elif action == "update_file":
                return await self._update_file(params, context)
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as e:
            log.error("github_plugin_error", action=action, error=str(e))
            return {"error": str(e)}
    
    async def _create_repo(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new GitHub repository."""
        name = params.get("name")
        description = params.get("description", "")
        private = params.get("private", False)
        
        if not name:
            return {"error": "Repository name is required"}
        
        # Stub implementation - would use GitHub API in production
        return {
            "success": True,
            "repo": {
                "name": name,
                "description": description,
                "private": private,
                "url": f"https://github.com/{self._default_owner or 'user'}/{name}",
            }
        }
    
    async def _list_repos(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """List repositories for an owner."""
        owner = params.get("owner", self._default_owner)
        
        # Stub implementation
        return {
            "success": True,
            "repos": [
                {"name": "example-repo", "private": False, "url": f"https://github.com/{owner}/example-repo"}
            ]
        }
    
    async def _create_issue(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Create an issue in a repository."""
        repo = params.get("repo")
        title = params.get("title")
        body = params.get("body", "")
        
        if not repo or not title:
            return {"error": "Repository and title are required"}
        
        # Stub implementation
        return {
            "success": True,
            "issue": {
                "number": 1,
                "title": title,
                "body": body,
                "state": "open",
                "url": f"https://github.com/{self._default_owner or 'user'}/{repo}/issues/1"
            }
        }
    
    async def _create_pr(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Create a pull request."""
        repo = params.get("repo")
        title = params.get("title")
        head = params.get("head")
        base = params.get("base", "main")
        body = params.get("body", "")
        
        if not repo or not title or not head:
            return {"error": "Repository, title, and head branch are required"}
        
        # Stub implementation
        return {
            "success": True,
            "pr": {
                "number": 1,
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "state": "open",
                "url": f"https://github.com/{self._default_owner or 'user'}/{repo}/pull/1"
            }
        }
    
    async def _get_file(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Get file content from a repository."""
        repo = params.get("repo")
        path = params.get("path")
        params.get("ref", "main")
        
        if not repo or not path:
            return {"error": "Repository and path are required"}
        
        # Stub implementation
        return {
            "success": True,
            "file": {
                "path": path,
                "content": "file content stub",
                "sha": "abc123"
            }
        }
    
    async def _update_file(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Update a file in a repository."""
        repo = params.get("repo")
        path = params.get("path")
        content = params.get("content")
        params.get("message", f"Update {path}")
        params.get("sha")
        
        if not repo or not path or not content:
            return {"error": "Repository, path, and content are required"}
        
        # Stub implementation
        return {
            "success": True,
            "file": {
                "path": path,
                "content": content,
                "sha": "def456"
            }
        }
    
    async def health_check(self) -> str:
        """Health check for the plugin."""
        try:
            # Check if token is configured
            if not self._token:
                return "degraded"
            return "ok"
        except Exception:
            return "unavailable"


# Register the plugin
def register_github_plugin():
    """Register the GitHub plugin with the plugin registry."""
    plugin = GitHubPlugin()
    registry = get_plugin_registry()
    if registry.register(plugin):
        log.info("github_plugin_registered")
        return plugin
    return None
