"""
jarvis-watcher — Monitor logs and detect anomalies.

Responsibilities:
    - Analyze application logs for errors and warnings
    - Detect anomalous patterns (spikes, repeated failures, new error types)
    - Monitor agent success/failure rates
    - Track system health metrics
    - Alert on critical issues

Tool access:
    - File read (logs, workspace/*.json, monitoring/)
    - Git log (recent activity)
    - Process listing (read-only)
    - Metrics files

Does NOT:
    - Modify code or configs
    - Restart services
    - Access external monitoring systems without configuration
"""
from __future__ import annotations

from agents.jarvis_team.base import JarvisTeamAgent
from core.state import JarvisSession


class JarvisWatcher(JarvisTeamAgent):
    name      = "jarvis-watcher"
    role      = "default"
    timeout_s = 120

    def system_prompt(self) -> str:
        return """You are jarvis-watcher, the monitoring and anomaly detection agent for JarvisMax.

Your job: keep an eye on system health and catch problems early.

What to watch:
- Application logs (errors, warnings, exceptions)
- Agent execution results (success rates, timeouts, failures)
- Mission completion rates
- System resource indicators
- Recent git activity (unexpected changes, reverts)

Anomaly detection:
- Repeated errors from the same module
- Agent success rate drops below 80%
- New error types not seen before
- Unusually long execution times
- Failed missions that were auto-approved

Output format:
```
## Watcher Report

### System Health: [HEALTHY|DEGRADED|CRITICAL]

### Observations
- [OK|WARN|CRITICAL] component — observation

### Anomalies detected
- description, severity, recommended action

### Metrics
- Missions: N completed, N failed (last 24h)
- Agent success rate: X%
- Recent errors: N
```

If everything looks healthy, say so concisely. Don't generate false alarms."""

    def user_message(self, session: JarvisSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)

        # Gather monitoring context
        night_reports = self.list_files("workspace/night_reports", "*.json")
        metrics_file = self.read_file("monitoring/metrics.py", max_chars=2000)

        mon_ctx = ""
        if night_reports:
            # Read most recent report
            latest = sorted(night_reports)[-1]
            report = self.read_file(latest, max_chars=3000)
            mon_ctx += f"\nLatest night report ({latest}):\n```\n{report}\n```\n"
        if metrics_file:
            mon_ctx += "\nMetrics module available: monitoring/metrics.py\n"

        return f"{ctx}{mon_ctx}\n\nMonitoring task:\n{task}"
