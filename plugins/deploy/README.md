# Deploy Plugin

Deployment plugin for Bea - provides deployment operations for Vercel, Railway, Docker, and other platforms.

## Installation

The plugin is automatically registered when Bea starts. Configure the following environment variables:

```bash
VERCEL_TOKEN=your_vercel_token
RAILWAY_TOKEN=your_railway_token
DEPLOY_DEFAULT_PLATFORM=vercel
```

## Usage

### Deploy to Vercel

```python
from plugins.plugin_registry import get_plugin_registry

registry = get_plugin_registry()
deploy_plugin = registry.get("deploy")

result = await deploy_plugin.invoke(
    "deploy_vercel",
    {
        "project_name": "my-app",
        "directory": "./dist",
        "environment": "production"
    },
    {}
)
```

### Deploy to Railway

```python
result = await deploy_plugin.invoke(
    "deploy_railway",
    {
        "project_name": "my-app",
        "directory": "./dist",
        "environment": "production"
    },
    {}
)
```

### Deploy as Docker Container

```python
result = await deploy_plugin.invoke(
    "deploy_docker",
    {
        "image_name": "my-app",
        "tag": "latest",
        "registry": "docker.io",
        "ports": ["80:80"]
    },
    {}
)
```

### Get Deployment Status

```python
result = await deploy_plugin.invoke(
    "get_status",
    {
        "deployment_id": "vercel_deploy_123",
        "platform": "vercel"
    },
    {}
)
```

### Rollback Deployment

```python
result = await deploy_plugin.invoke(
    "rollback",
    {
        "deployment_id": "vercel_deploy_123",
        "target_version": "v1.0.0"
    },
    {}
)
```

## Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `deploy_vercel` | `project_name`, `directory`, `environment` | Deploy to Vercel |
| `deploy_railway` | `project_name`, `directory`, `environment` | Deploy to Railway |
| `deploy_docker` | `image_name`, `tag`, `registry`, `ports` | Deploy as Docker container |
| `get_status` | `deployment_id`, `platform` | Get deployment status |
| `rollback` | `deployment_id`, `target_version` | Rollback deployment |

## Permissions

The plugin requires the following permissions:
- **Secret**: `VERCEL_TOKEN` - Vercel API token
- **Secret**: `RAILWAY_TOKEN` - Railway API token
- **Config**: `DEPLOY_DEFAULT_PLATFORM` - Default deployment platform

## Risk Level

**High** - This plugin can deploy applications and modify infrastructure. Ensure proper API token permissions are configured and limit access to production environments.

## Manifest

```json
{
  "plugin_id": "deploy",
  "name": "Deployment Operations",
  "version": "1.0.0",
  "description": "Deploy applications to Vercel, Railway, Docker, and other platforms",
  "author": "Bea Team",
  "risk_level": "high",
  "required_secrets": ["VERCEL_TOKEN", "RAILWAY_TOKEN"],
  "required_configs": ["DEPLOY_DEFAULT_PLATFORM"]
}
```
