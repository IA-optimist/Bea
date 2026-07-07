# Verifier v0 — Security Broker

## What it is

Verifier v0 is a minimal, deterministic, fail-closed security broker that intercepts
all effectful actions before they reach the real world.

**No LLM. No natural language parsing. No exceptions (literally — fail-closed).**

## Architecture

```
Béa (cognitive layer)
    │
    │  ActionIntent (structured, immutable, frozen)
    ▼
VerifierBroker.execute()
    │
    ├─► VerifierPolicy.evaluate()   ← deterministic rules only, stateless
    │       │
    │       └─ HALT > HOLD > DENY > allowlist > DENY default
    │
    ├─► VerifierAuditLog.record()   ← append-only, parameters never logged
    │
    └─► Effectuor (real action)     ← only if verdict = ALLOW + effectuor wired
```

Béa holds only opaque `ActionIntent` objects. The broker holds effectuors.
If the broker fails, no action is possible (fail-closed by design).

## Verdicts

| Verdict | Meaning | Exception raised |
|---------|---------|-----------------|
| `ALLOW` | Action allowed, dispatched to effectuor | — |
| `DENY`  | Action blocked, logged | `VerifierDenied` |
| `HOLD`  | Suspended — human approval required | `VerifierHoldRequired` |
| `HALT`  | Critical violation — halt recommended | `VerifierHaltTriggered` |

If the broker itself fails: `VerifierUnavailable` (fail-closed).

## What Verifier v0 PROTECTS

All calls routed through `VerifierBroker.execute()` are subject to policy:

**HALT targets (any action targeting these):**
- Verifier itself (`verifier` in path)
- Audit logs (`audit.log`, `audit_log` in path)
- Credentials (`credential` in path)
- Kill-switch (`kill-switch` in path)
- Environment files (`.env`)
- Secrets (`secret` in path)
- Security/sandbox config files
- Capability registry
- `policy.py`

**Always HOLD (requires human approval):**
- `SELF_MODIFICATION`
- `SPAWN_AGENT`
- `MODIFY_MEMORY`
- Filesystem writes outside allowed workspace
- Network requests to non-whitelisted domains
- API calls to unknown services

**Always DENY:**
- `EXEC_COMMAND` (no sandbox authorization in v0)
- Actions not on the allowlist
- Internal policy errors (fail-closed)

**Ignored by policy (audit-only):**
- `intent.metadata` — never read by policy
- `intent.risk_hint` — caller-provided, never trusted
- Any free-text justification — not a policy input

## What Verifier v0 DOES NOT YET PROTECT

⚠️ **v0 is an interface layer, not full runtime enforcement.**

The following are NOT yet wired through the broker:

| Effectuor | Status |
|-----------|--------|
| Direct `open()` / `pathlib` file I/O in existing code | NOT WIRED |
| `subprocess` calls in existing code | NOT WIRED |
| HTTP requests made by existing modules | NOT WIRED |
| Agent-to-agent calls in `crew.py` / `meta_orchestrator.py` | NOT WIRED |
| `core/tool_executor.py` tool dispatch | NOT WIRED |
| Telegram bot send functions | NOT WIRED |

**"ALLOW" verdicts on unwired effectuors mean the policy passed, not that the real action ran through the broker.**

See `INTEGRATION_STATUS` in `broker.py` for current status.

## Fail-closed guarantees

| Failure | Result |
|---------|--------|
| Policy internal exception | DENY verdict returned (never raised) |
| Audit log write failure | `VerifierUnavailable` raised |
| Unknown verdict from policy | `VerifierUnavailable` raised |
| Broker not instantiated | Action impossible (caller must have broker reference) |

## Usage

```python
from agent_security.verifier import VerifierBroker, ActionIntent, ActionType, EffectScope
from agent_security.verifier.exceptions import VerifierDenied, VerifierHoldRequired, VerifierHaltTriggered

broker = VerifierBroker()

intent = ActionIntent(
    actor_id="bea-agent",
    action_type=ActionType.FILESYSTEM_READ,
    target="/workspace/report.md",
    declared_scope=EffectScope.LOCAL_READONLY,
)

try:
    decision = broker.execute(intent)
    # verdict = ALLOW — action dispatched to effectuor (if wired)
except VerifierDenied as e:
    # blocked — log and stop
except VerifierHoldRequired as e:
    # queue for human approval
except VerifierHaltTriggered as e:
    # critical — alert, recommend shutdown
```

## Wiring a real effectuor

```python
def my_filesystem_reader(intent: ActionIntent) -> bytes:
    return Path(intent.target).read_bytes()

broker.register_effectuor("filesystem_read", my_filesystem_reader)
```

Only the infrastructure bootstrap layer should call `register_effectuor`.
Béa's cognitive layer never has access to effectuors directly.

## Running tests

```bash
python -m pytest tests/agent_security/ -v --tb=short
```

## v1 roadmap — making Verifier mandatory everywhere

1. Wire `core/tool_executor.py` dispatch through broker
2. Wire HTTP client (used by API calls, Telegram, etc.)
3. Wire agent spawn in `meta_orchestrator.py` / `crew.py`
4. Wire file I/O in coding agent
5. Add HOLD queue with human-approval UI (webhook or Telegram callback)
6. Add capability token system (Béa requests tokens, broker grants scoped access)
7. Add rate limiting enforcement in broker (not just logging)
8. Add structured invariant checks on ALLOW decisions
9. Integrate with `kernel/improvement/gate.py` for self-improvement gate
