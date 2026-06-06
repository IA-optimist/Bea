# Log event-name convention

**Audit reference:** observability quick-win #5.
**Enforcement:** `tests/test_log_event_name_convention.py`.

## The rule (going forward)

Every `log.<level>(...)` call's first positional argument is the
**event name**. Event names MUST follow this regex:

```
^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$
```

In English:

  - Lowercase only.
  - Start with a letter.
  - Body: ASCII letters, digits, underscores.
  - Optionally namespaced with **dots** (`<module>.<event>`),
    where each segment also follows the same shape.

Examples that pass:

| Event | Note |
|---|---|
| `mission_complete` | bare event |
| `agent_start` | bare event |
| `swallowed_exception` | M3 canonical (introduced in the hardening pass) |
| `jwt_v2_family_revoked` | Mo2 canonical |
| `metrics_bridge.patched` | namespaced ; subsystem dot event |
| `canonical_mission_store.ready` | namespaced ; module dot state |
| `daemon.proposals_generated` | namespaced ; module dot verb |

Examples that fail:

| Event | Reason |
|---|---|
| `MissionComplete` | uppercase letters |
| `mission complete` | contains a space |
| `mission-complete` | contains a dash (use underscore) |
| `1mission_complete` | starts with a digit |
| `mission_complete!` | special character |
| `agent.` | trailing dot |

## Rationale

- **Lowercase + snake_case** matches every other key the codebase emits
  (audit observability §S — `mission_id`, `err`, `action`, etc.).
- **Dot namespacing** lets Loki / Datadog / Grafana group events by
  subsystem without parsing the message body — `{event=~"daemon\\..+"}`
  is a one-line dashboard filter.
- **No dashes** because Prometheus and several log shippers treat
  dashes as syntax in their query DSLs.

## What about existing violations?

The convention is enforced going forward only. The enforcement test
loads `quality/legacy_log_event_names.json` — a 54-entry baseline of
the event names that DID NOT pass when this gate was first added
(audit 2026-05-29). The top-30 frequency leaders already comply ; the
long tail contains sentences accidentally used as event names
("Admin login attempted but JARVIS_ADMIN_PASSWORD is not set…") and
prefixed lines that mix message + key ("rate_limit.memory_storage —
REDIS_URL not set…").

The gate enforces three things:

  1. **No new violation** — any `log.<level>("X", ...)` call where `X`
     is neither in the baseline nor matches the regex fails CI.
  2. **No upward drift in the baseline** — the baseline is locked
     to its current size ; fixing one of the 54 events removes its
     entry. Adding entries means writing a justification in the PR.
  3. **Baseline stays tight** — if a grandfathered event is no
     longer emitted (file got deleted, code got refactored), drop the
     entry. The third test in the file catches stale entries.

Fixing a baseline entry is a 30-second change: rename the event to
`subsystem_action_state` shape, rerun the test, commit the trimmed
JSON. No need to coordinate dashboards because none of the legacy
event names are stable enough to be dashboarded today.

## Recurring suspect: exception swallow events

When you catch and absorb an exception, follow the M3 pattern:

```python
try:
    risky()
except Exception as exc:
    log.warning(
        "swallowed_exception",                # event name
        action="describe_what_was_attempted", # subject of the operation
        exc_type=type(exc).__name__,
        exc_msg=str(exc)[:200],
    )
```

Or, for new code, use the helper:

```python
from core._logging_helpers import swallow

with swallow(log, action="describe_what_was_attempted"):
    risky()
```

The helper does the WARNING-level emission with the same key shape, so
the dashboard query `{event="swallowed_exception"}` catches both old
manual sites and new helper-driven sites.

## Re-running this audit

```bash
# Event-name distribution (first arg of log.*(.))
grep -rhE 'log\.(info|warning|error|debug)\(\s*["'\''](\w[\w.]*)' \
  --include='*.py' api/ core/ kernel/ agents/ \
  | sed 's/.*log\.[a-z]*(\s*["'\'']//;s/["'\''].*//' \
  | sort | uniq -c | sort -rn | head -30
```
