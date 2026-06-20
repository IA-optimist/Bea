# GitHub Plugin

GitHub integration plugin for Bea - provides repository management, issue tracking, and PR operations.

## Installation

The plugin is automatically registered when Bea starts. Ensure the following environment variables are configured:

```bash
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxxxxxxxxxxx
GITHUB_DEFAULT_OWNER=your-username
```

## Usage

### Create a Repository

```python
from plugins.plugin_registry import get_plugin_registry

registry = get_plugin_registry()
github_plugin = registry.get("github")

result = await github_plugin.invoke(
    "create_repo",
    {
        "name": "my-new-repo",
        "description": "A new repository",
        "private": False
    },
    {}
)
```

### List Repositories

```python
result = await github_plugin.invoke(
    "list_repos",
    {"owner": "your-username"},
    {}
)
```

### Create an Issue

```python
result = await github_plugin.invoke(
    "create_issue",
    {
        "repo": "my-repo",
        "title": "Bug found",
        "body": "Detailed description of the bug"
    },
    {}
)
```

### Create a Pull Request

```python
result = await github_plugin.invoke(
    "create_pr",
    {
        "repo": "my-repo",
        "title": "Fix bug",
        "head": "feature-branch",
        "base": "main",
        "body": "Description of changes"
    },
    {}
)
```

### Get File Content

```python
result = await github_plugin.invoke(
    "get_file",
    {
        "repo": "my-repo",
        "path": "README.md",
        "ref": "main"
    },
    {}
)
```

### Update File

```python
result = await github_plugin.invoke(
    "update_file",
    {
        "repo": "my-repo",
        "path": "README.md",
        "content": "Updated content",
        "message": "Update README",
        "sha": "abc123"
    },
    {}
)
```

## Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `create_repo` | `name`, `description`, `private` | Create a new repository |
| `list_repos` | `owner` | List repositories for an owner |
| `create_issue` | `repo`, `title`, `body` | Create an issue |
| `create_pr` | `repo`, `title`, `head`, `base`, `body` | Create a pull request |
| `get_file` | `repo`, `path`, `ref` | Get file content |
| `update_file` | `repo`, `path`, `content`, `message`, `sha` | Update file in repository |

## Permissions

The plugin requires the following permissions:
- **Secret**: `GITHUB_PERSONAL_ACCESS_TOKEN` - GitHub personal access token
- **Config**: `GITHUB_DEFAULT_OWNER` - Default GitHub username/organization

## Risk Level

**Medium** - This plugin can modify repositories and create issues/PRs. Ensure proper access token permissions are configured.

## Manifest

```json
{
  "plugin_id": "github",
  "name": "GitHub Integration",
  "version": "1.0.0",
  "description": "GitHub repository management, issues, and PR operations",
  "author": "Bea Team",
  "risk_level": "medium",
  "required_secrets": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  "required_configs": ["GITHUB_DEFAULT_OWNER"]
}
```
