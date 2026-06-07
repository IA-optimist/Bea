"""
bea-devops — Deployment and environment validation.

Responsibilities:
    - Validate Docker configurations (docker-compose.yml, Dockerfiles)
    - Check CI/CD pipeline health (.github/workflows/)
    - Verify environment dependencies (requirements, pyproject.toml)
    - Validate deployment readiness
    - Check service health post-deployment

Tool access:
    - File read (configs, dockerfiles, CI files)
    - Git status/diff
    - Docker commands (inspect, ps — read-only)
    - Process listing
    - Environment variable inspection (names only, not values)

Does NOT:
    - Deploy to production without approval
    - Modify production configs directly
    - Access secrets or API keys
    - Restart running services without approval
"""
from __future__ import annotations

from agents.bea_team.base import BeaTeamAgent
from core.state import BeaSession


class BeaDevOps(BeaTeamAgent):
    name      = "bea-devops"
    role      = "builder"
    timeout_s = 180

    def system_prompt(self) -> str:
        return """You are bea-devops, the deployment and infrastructure agent for BeaMax.

Your job: ensure the system can be built, deployed, and run reliably.

Scope:
- Docker: docker-compose.yml, docker-compose.prod.yml, Dockerfiles
- CI/CD: .github/workflows/*.yml
- Dependencies: requirements.txt, pyproject.toml, setup.py
- Environment: required env vars, ports, volumes
- Health: service status, port availability, log errors

Validation checklist:
1. **Build** — Can docker-compose build succeed?
2. **Dependencies** — Are all imports satisfiable? Version conflicts?
3. **Config** — Are required env vars documented? Defaults safe?
4. **CI** — Do workflow files reference existing scripts and paths?
5. **Ports** — Any conflicts? Are health check endpoints defined?

Output format:
```
## DevOps Report

### Environment
- Python: X.Y
- Docker: available/unavailable
- CI: N workflow files

### Issues
- [SEVERITY] description

### Recommendations
- suggestion

### Deployment readiness: [READY|BLOCKED|NEEDS_REVIEW]
```

Never run destructive commands. Read-only inspection only unless explicitly asked."""

    def user_message(self, session: BeaSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)

        # Gather environment context
        docker_compose = self.read_file("docker-compose.yml", max_chars=3000)
        ci_files = self.list_files(".github/workflows", "*.yml")

        env_ctx = ""
        if docker_compose:
            env_ctx += f"\ndocker-compose.yml:\n```yaml\n{docker_compose}\n```\n"
        if ci_files:
            env_ctx += f"\nCI workflows: {', '.join(ci_files)}\n"

        return f"{ctx}{env_ctx}\n\nDevOps task:\n{task}"
