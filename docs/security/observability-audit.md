# Observability audit — Prometheus + structlog

**Audit reference:** observability follow-up.
**Status:** findings + recommendations. Fixes intentionally deferred per
finding because most touch dashboards / alerts / log queries the team
already runs.

## Method

- Prometheus: scanned every module-level `Counter` / `Histogram` /
  `Gauge` / `Summary` instantiation under `api/`, `core/`, `kernel/`,
  `agents/`, `business/`, `memory/`.
- structlog: counted the frequency of every `log.<level>(...)` keyword
  argument in the same scope. The top-30 keys cover ~95% of log lines.

Methodology lives in this doc so re-running the audit after a cleanup
PR is one grep away.

## Prometheus — current state

### Active service metrics

| Module | Metric (exported name) | Type | Labels |
|---|---|---|---|
| `core/profiling.py` | `jarvis_profile_duration_seconds` | Histogram | `span`, `status` |
| `api/jwt_v2.py` | `jarvis_jwt_v2_pairs_issued_total` | Counter | `origin` (login / rotation) |
| `api/jwt_v2.py` | `jarvis_jwt_v2_rotations_total` | Counter | `outcome` (ok / replay / unknown) |
| `api/jwt_v2.py` | `jarvis_jwt_v2_revocations_total` | Counter | `kind` (access / refresh / family) |
| `business/business_engine.py` | `business_opportunity_scans_total` | Counter | — |
| `business/business_engine.py` | `business_opportunities_found` | Gauge | — |
| `business/business_engine.py` | `business_scan_duration_seconds` | Histogram | — |
| `business/business_engine.py` | `business_product_builds_total` | Counter | — |
| `business/business_engine.py` | `business_deploy_duration_seconds` | Histogram | — |
| `business/business_engine.py` | `business_compliance_checks_total` | Counter | — |
| `business/business_engine.py` | `business_pipeline_runs_total` | Counter | — |

### Findings

**P1 — Prefix split** (medium). Two prefixes coexist:
  - `jarvis_*` (4 metrics: profiling + 3 jwt_v2 counters)
  - `business_*` (7 metrics: all of business_engine)

Prometheus best practice is to use a single service prefix so dashboards
can `up{job="jarvis"}` and metrics are easy to discover via the registry.
The `business_*` prefix predates the `jarvis_*` one.

**Recommendation:**
  - Going forward, all new metrics MUST use `jarvis_<subsystem>_<thing>_<unit>`.
  - Migrate `business_*` to `jarvis_business_*` with dual emission for one
    release cycle:
    ```python
    OPPORTUNITY_SCANS = Counter('business_opportunity_scans_total', ...)
    OPPORTUNITY_SCANS_NEW = Counter('jarvis_business_opportunity_scans_total', ...)
    # increment both in the same call site; remove the old name after dashboards swap
    ```
  - Add a CI test asserting every new Counter starts with `jarvis_` and
    ends with `_total`. (Skeleton: see `tests/test_jwt_v2_metrics.py::test_metric_names_follow_convention`.)

**P2 — Counter `_total` convention** (good). All 7 Counters use the
`_total` suffix. The Prometheus client library auto-appends `_total` if
absent ; pinning it explicitly avoids surprise.

**P3 — Histogram `_seconds` convention** (good). The two Histograms
(`*_duration_seconds`, `*_scan_duration_seconds`) use the SI suffix.
No `_milliseconds` / `_minutes` anywhere — consistent.

**P4 — Gauge naming** (minor). `business_opportunities_found` is a
Gauge with no suffix. Gauges don't have a fixed convention, but a
suffix that hints at the value (`_count`, `_bytes`, `_ratio`) helps
dashboards. `business_opportunities_found_count` would be clearer.

**P5 — Label cardinality** (good). All labels are bounded enums (`origin`,
`outcome`, `kind`, `span`, `status`). No high-cardinality risks like
user IDs or paths.

**P6 — `core/profiling.py` registration gate** (good). Wrapped in
`try/except Exception` so prometheus_client absence does not break
profiling itself. Pattern matches what `api/jwt_v2.py` now does.

## structlog — current state

### Top-30 keys (frequency across api/ core/ kernel/ agents/)

| Count | Key | Note |
|---|---|---|
| 632 | `err=` | **Canonical** — keep |
| 424 | `src=` | Often a file path or component name |
| 80 | `error=` | **Duplicate of `err=`** — migrate |
| 79 | `mission_id=` | Canonical |
| 38 | `name=` | Generic ; context-dependent |
| 38 | `location=` | Path-ish |
| 35 | `count=` | OK |
| 33 | `path=` | OK |
| 31 | `agent=` | **Canonical** (vs 4× `agent_id=`) |
| 30 | `id=` | **Too generic** ; prefer `<thing>_id=` |
| 26 | `reason=` | OK |
| 22 | `target=` | OK |
| 20 | `phase=` | OK |
| 16 | `tool=` | OK |
| 15 | `mode=` | OK |
| 14 | `run_id=` | OK |
| 12 | `stage=` | OK |
| 12 | `sid=` | **Short for session_id** — migrate to `mission_id=` (canonical) |
| 10 | `type=` | Generic, context-dependent |
| 10 | `ms=` | Latency, OK |

### Findings

**S1 — `err` vs `error`** (small, ratchetable). 632 `err=` calls vs 80
`error=`. Both carry the same payload (`str(exc)[:N]`). Pick one
(recommended: `err=` since it's 8× more common) and migrate the 80
holdouts. Easy with `git grep -l "error=" -- '*.py' | xargs sed -i`.

**S2 — `sid` vs `mission_id`** (medium). 12 `sid=` sites use a short
alias for what is everywhere else called `mission_id`. Mixed naming
makes log queries fragile :
```
# Today you need both:
mission_id="abc" OR sid="abc"
```
Migrate the 12 `sid=` sites to `mission_id=`. They live in
`agents/crew.py` and 1-2 other files (`git grep "sid=" -- '*.py'`).

**S3 — `agent=` vs `agent_id=`** (small). 33 `agent=` vs 4 `agent_id=`.
The `agent=` form is dominant and carries the agent **name**, not an
id. Rename the 4 `agent_id=` sites to `agent=` (or convert the value to
match the convention).

**S4 — Bare `id=`** (medium). 30 sites use `id=...` without a prefix.
Either a `mission_id`, `agent_id`, `tool_id`, `action_id`, depending on
context. When grouping logs in Loki / Datadog this means a wildcard
`id=*` matches everything and can't be narrowed. Migrate to typed keys.

**S5 — Event name convention** (medium, no fix). Event names (`log.info("X", ...)`
first argument) follow no convention :
```
log.info("mission_complete", ...)
log.info("opportunity_scan_complete", ...)
log.info("repo_context_injected", ...)
log.warning("swallowed_exception", ...)        # new (M3)
log.warning("jwt_v2_family_revoked", ...)      # new (Mo2)
```
The dominant pattern is `<subsystem>_<verb>` or `<subsystem>_<event>_<state>`.
The newly-introduced ones (`swallowed_exception`, `jwt_v2_*`) already
follow this. Worth committing the convention to a one-pager and adding
a soft lint (regex `^[a-z][a-z_]*[a-z]$` on the first arg of `log.*(`).

**S6 — Exception capture convention** (good, new). The recently
introduced `swallowed_exception` events all carry `action`, `exc_type`,
`exc_msg` consistently (see `core/_logging_helpers.swallow`). This is
the model to follow for any new exception-swallowing site.

**S7 — `src=` is verbose but useful** (no fix). 424 sites use
`src=__file__`. In structured logs this duplicates the structlog
`module` processor, but it does survive when the log line is reshipped
without the processor context. Borderline ; leave alone.

## Quick wins ranked by ROI

| # | Action | Effort | Risk | Reach |
|---|---|---|---|---|
| 1 | Add CI metric-naming gate (Counter must `jarvis_*…_total`, Histogram must `*_seconds` or `*_bytes`) | 30 min | None | Locks future naming |
| 2 | `sid=` → `mission_id=` migration (12 sites) | 30 min | Low | Cleaner log queries |
| 3 | Document event-name convention in `docs/observability/log-events.md` + soft lint | 1 h | None | Discoverability |
| 4 | `error=` → `err=` migration (80 sites) | 1 h | Low | Unified payload key |
| 5 | Rename Gauge `business_opportunities_found` → `business_opportunities_found_count` | 15 min | **Breaks any dashboard using it** — coordinate first | Convention |
| 6 | Bare `id=` → typed `<thing>_id=` (30 sites) | 2 h | Low ; each site needs context inspection | Loki/Datadog queries |
| 7 | `business_*` → `jarvis_business_*` with dual emission | 1 day + dashboard swap | **Breaks dashboards/alerts using old names** — needs coordination | Single-prefix story |

Items 1–3 are no-coordination wins. Items 4 is a mechanical sed pass.
Items 5–7 require coordinating with whoever owns the dashboards before
landing.

## Already-fixed during the hardening pass

- `jwt_v2.py` metrics follow `jarvis_jwt_v2_*_total` from day one.
- `swallowed_exception` events have a uniform `action`/`exc_type`/`exc_msg` shape.
- `core/profiling.py` already uses `jarvis_profile_duration_seconds`.

## Re-running this audit

```bash
# Prometheus metric definitions
grep -rEn '^\s*\w+\s*=\s*(Counter|Histogram|Gauge|Summary)\(' \
  --include='*.py' api/ core/ kernel/ agents/ business/ memory/

# structlog key frequency (top N)
grep -rhE 'log\.(info|warning|error|debug)\(' --include='*.py' \
  api/ core/ kernel/ agents/ | grep -oE '\w+=' | sort | uniq -c | sort -rn | head -30

# Event-name distribution (first arg of log.*(.))
grep -rhE 'log\.(info|warning|error|debug)\(\s*["'\''](\w+)' --include='*.py' \
  api/ core/ kernel/ agents/ | sed 's/.*log\.[a-z]*(\s*["'\'']//;s/["'\''].*//' \
  | sort | uniq -c | sort -rn | head -30
```
