# Autonomy Layer — User Guide

## What it is

The autonomy layer turns JarvisMax from "reactive mission-runner" into
"goal-driven actor". It runs a daemon thread that picks the next
concrete action toward an objective, executes it via the existing
MetaOrchestrator, and stops when it hits a budget / failure / time
cap.

Designed to stay **safe by default** :

- Risky actions still flow through `core.approval_queue` (no bypass)
- Hard daily budget caps via env vars (`JARVIS_AUTONOMY_DAILY_USD_MAX`)
- Operator emergency halt : `export JARVIS_AUTONOMY_PAUSED=1`
- Real-orchestrator mode is opt-in : `JARVIS_AUTONOMY_USE_REAL=1`
- The daemon publishes every iteration on the event bus — full audit trail

## Architecture

```
core/autonomy/
├── event_bus.py        ← in-process pub/sub (glob topics, replay buffer)
├── budget.py           ← per-mission + daily token/$/time/failure caps
├── stop_conditions.py  ← composable predicates (timeout, confidence, …)
├── daemon.py           ← AutonomyDaemon : run_once() / run_forever()
├── skills.py           ← @register_skill decorator + registry
├── builtin_skills.py   ← 5 default skills (noop, health, cache, budget, events)
├── learning.py         ← OutcomeLearner : EWMA decay on action/skill outcomes
├── multi_choice.py     ← multi-option HITL decisions (beyond approve/reject)
├── runners.py          ← meta_orchestrator_runner, composite_runner
├── planners.py         ← objective_engine_planner, learner_aware_planner
└── approval_bridge.py  ← StrategyChoice + request_strategy_choice
```

## Operator flow

1. **Boot once** : `bash scripts/install_autonomy.sh` (on VPS1, root).
   This installs the systemd unit + `/etc/jarvismax/autonomy.env`.

2. **Edit the objective** : `vim /etc/jarvismax/autonomy_objective.txt`.

3. **Set the API process env var** : in `docker-compose.yml`
   ```yaml
   services:
     jarvis_core:
       environment:
         JARVIS_AUTONOMY_USE_REAL: "1"
         JARVIS_AUTONOMY_DAILY_USD_MAX: "20"
   ```
   Then `docker compose up -d` to restart.

4. **Start the daemon** :
   ```bash
   systemctl start jarvis-autonomy
   # OR via API directly :
   curl -X POST https://jarvis.../api/v3/autonomy/start \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"objective": "...", "max_iters": 20, "sleep_s": 30}'
   ```

5. **Monitor** :
   ```bash
   curl https://jarvis.../api/v3/autonomy/status
   # OR open the mobile app → Approbations → ⊕ icon → Decisions
   ```

6. **Halt** :
   ```bash
   curl -X POST https://jarvis.../api/v3/autonomy/stop -d '{"reason":"manual"}'
   # Emergency kill switch :
   docker exec jarvis_core sh -c 'export JARVIS_AUTONOMY_PAUSED=1'
   ```

## REST API

| Method | Path | Description |
|---|---|---|
| POST | `/api/v3/autonomy/start` | Spawn daemon thread (one per process ; force=true to replace) |
| POST | `/api/v3/autonomy/stop` | Graceful stop, returns iteration summary |
| GET | `/api/v3/autonomy/status` | Read-only state + budget + recent events |
| GET | `/api/v3/autonomy/decisions` | List pending multi-choice decisions |
| POST | `/api/v3/autonomy/decisions/{id}/answer` | Operator answers a decision |

All endpoints require auth (`Authorization: Bearer <token>` or cookie).

## Event topics

The daemon publishes on the in-process event bus. Subscribers can react
in real-time (e.g. send a Telegram notification on `decision.created`).

| Topic | Payload |
|---|---|
| `autonomy.iteration.started` | objective, iteration, action |
| `autonomy.iteration.completed` | confidence, tokens, usd |
| `autonomy.iteration.failed` | error, confidence |
| `autonomy.objective.changed` | objective |
| `autonomy.action.requested` | action, payload (default runner) |
| `autonomy.halted` | reason (budget / stop_policy / paused / max_iters) |
| `skill.invoked` / `skill.completed` / `skill.failed` | skill, duration_s |
| `decision.created` / `decision.answered` / `decision.timed_out` | decision_id |

Subscribe :
```python
from core.autonomy import get_event_bus
bus = get_event_bus()
bus.subscribe("autonomy.halted", lambda e: print("Daemon halted:", e.payload))
```

## Budget and stop conditions

Defaults (per mission) :

| Limit | Default | Override env var |
|---|---|---|
| Wall time | 30 minutes | per-call |
| Iterations | 50 | per-call |
| Tokens | 100k | per-call |
| USD | $1 | per-call |
| Consecutive failures | 3 | per-call |

Defaults (daily, process-wide) :

| Limit | Default | Override env var |
|---|---|---|
| Tokens | 5M | `JARVIS_AUTONOMY_DAILY_TOKENS_MAX` |
| USD | $50 | `JARVIS_AUTONOMY_DAILY_USD_MAX` |

The daemon halts as soon as ANY limit is hit and emits
`autonomy.halted` with the reason.

## Common patterns

### Watch a metric and react

```python
from core.autonomy import get_event_bus
bus = get_event_bus()

def on_high_cpu(event):
    if event.payload.get("cpu_percent", 0) > 90:
        # Trigger a multi-choice decision
        from core.autonomy.approval_bridge import (
            request_strategy_choice, StrategyChoice,
        )
        request_strategy_choice(
            name="high_cpu",
            question=f"CPU at {event.payload['cpu_percent']}%. Which action?",
            strategies=[
                StrategyChoice(label="restart_container", risk_level="medium"),
                StrategyChoice(label="scale_up", risk_level="low"),
                StrategyChoice(label="ignore", risk_level="low"),
            ],
            default_strategy_index=2,  # default = ignore on timeout
            timeout_s=300,
        )

bus.subscribe("metric.cpu.high", on_high_cpu)
```

### Register a custom skill

```python
from core.autonomy.skills import register_skill, SkillContext, SkillResult

@register_skill(
    name="health-check-prod",
    description="Probe production API and report",
    tags=["ops", "health"],
)
def health_check_prod(ctx: SkillContext) -> SkillResult:
    import requests
    try:
        r = requests.get("https://jarvis.../api/v2/health", timeout=5)
        return SkillResult(success=r.ok, output={"status_code": r.status_code})
    except Exception as exc:
        return SkillResult(success=False, error=str(exc))
```

The skill is now invokable :
```python
from core.autonomy import get_skill_registry
result = get_skill_registry().get("health-check-prod").run()
```

### Connect outcomes to future decisions

The `OutcomeLearner` is auto-wired to the bus. The
`learner_aware_planner` reads its scores when ranking strategies :
recently-failing actions get downgraded automatically.

```python
from core.autonomy import get_outcome_learner
learner = get_outcome_learner()
# After 1 day of operation :
print(learner.snapshot())
# {'action:scan': {'score': 0.72, 'confidence': 0.83, 'successes': 14, 'failures': 5}, …}
```

## Safety guarantees recap

| Concern | Mitigation |
|---|---|
| Runaway LLM costs | Daily $$ cap (env var) ; per-mission $$ cap |
| Infinite loop | iteration cap + wall-clock cap |
| Repeated failures | Stop after 3 consecutive failures |
| Risky action without operator OK | ApprovalQueue + MultiChoice gate |
| Process crash | systemd Restart=on-failure with 30 s back-off |
| Real-mode accidentally on | Off by default ; needs `JARVIS_AUTONOMY_USE_REAL=1` |
| Need emergency halt | `export JARVIS_AUTONOMY_PAUSED=1` ; effective at next iteration |

## Tests

99 unit tests across 7 files :

- `tests/test_autonomy_event_bus.py` (12)
- `tests/test_autonomy_budget.py` (11)
- `tests/test_autonomy_daemon.py` (17)
- `tests/test_autonomy_skills.py` (11)
- `tests/test_autonomy_learning.py` (9)
- `tests/test_autonomy_multi_choice.py` (17)
- `tests/test_autonomy_wiring.py` (22)
- `tests/test_autonomy_api.py` (11) — FastAPI TestClient against the router

Run all :
```bash
pytest tests/test_autonomy_*.py -v
```

## Status

| Capability | Status |
|---|---|
| EventBus pub/sub | ✅ |
| Budget tracking | ✅ |
| Composable stop conditions | ✅ |
| Goal-driven daemon | ✅ |
| Skill registry + 5 builtins | ✅ |
| Outcome learning (EWMA) | ✅ |
| Multi-choice HITL | ✅ |
| MetaOrchestrator runner | ✅ (feature-flagged) |
| ObjectiveEngine planner | ✅ (feature-flagged) |
| REST control plane | ✅ |
| Mobile UI | ✅ (DecisionsScreen) |
| systemd auto-start | ✅ (deploy/jarvis-autonomy.service) |

The next big work is **product**, not code : define real objectives,
populate the ObjectiveEngine, and observe how the daemon behaves with
production traffic.
