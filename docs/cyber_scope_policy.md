# CyberScopePolicy — Reference

## Purpose

Every cyber mission **must** have an explicit `CyberScopePolicy` before any action is taken. No scope = no action (deny-by-default).

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `mission_id` | `str` | Links scope to a Béa mission |
| `requested_by` | `str` | Who requested this assessment |
| `authorization_status` | `AuthorizationStatus` | EXPLICIT / MISSING / UNKNOWN |

## Key Properties

| Property | Default | Description |
|----------|---------|-------------|
| `report_only` | `True` | When True, blocks modifying actions (propose_fix) |
| `max_requests` | `0` | Max external HTTP requests (0 = local only) |
| `risk_level` | `LOW` | Scope risk level — HIGH/CRITICAL require approval |
| `expires_at` | `None` | Scope expiry — expired scope blocks all actions |

## Authorization Rules

| Scenario | Result |
|----------|--------|
| External target + `EXPLICIT` auth | Allowed (if action is in allowed list) |
| External target + `MISSING` auth | **BLOCKED** |
| External target + `UNKNOWN` auth | **BLOCKED** |
| Local target (`localhost`, `127.0.0.1`) | Authorization status ignored |

## Local vs External

A scope is **local-only** when:
- `targets` is empty, OR
- All targets are `localhost`, `127.0.0.1`, `::1`, or start with `local:`

Local-only scopes do NOT require `EXPLICIT` authorization.

## Scope Examples

### Minimal local scope

```python
scope = CyberScopePolicy(
    mission_id="m-001",
    requested_by="security-bot",
)
# is_local_only = True, no auth needed
```

### External authorized scope

```python
scope = CyberScopePolicy(
    mission_id="m-002",
    requested_by="security-team",
    authorization_status=AuthorizationStatus.EXPLICIT,
    authorization_ref="pentest-2026-001",
    targets=["target.example.com"],
    allowed_hosts=["target.example.com"],
    allowed_ports=[80, 443],
    max_requests=100,
    expires_at=datetime.utcnow() + timedelta(hours=8),
    risk_level=RiskLevel.HIGH,
)
```
