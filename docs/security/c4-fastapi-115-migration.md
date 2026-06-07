# C4 — FastAPI 0.109 → 0.115 Migration Plan

**Status:** prep done, migration deferred to a dedicated PR.
**Audit reference:** C4.

## What the bump fixes

Direct CVE closures (transitive via Starlette 0.40+):

- **CVE-2024-47874** — Starlette multipart `Content-Type` DoS.
- **CVE-2025-54121** — Starlette `MultiPartParser` allocation DoS.

Both are tracked as deferred TODOs in `requirements.txt` lines 17-20.

## What we tested

A side virtualenv (`.venv-c4-prep/`, gitignored) was built with the
target stack pinned :

```
fastapi==0.115.6
starlette==0.41.3
pydantic==2.13.4  (unchanged)
pydantic-settings>=2.0
python-multipart>=0.0.20
uvicorn[standard]
```

Smoke harness — `scripts/c4_fastapi_115_smoke.py` — imports a graded list
of modules (config → auth → routes → app factory) under the new stack.
Test suite — `pytest tests/test_p1_hardening.py tests/test_jwt_v2.py
tests/test_auth_routes_v2_flag.py tests/test_logging_helpers.py
tests/test_architecture_size_gate.py tests/test_no_new_silent_swallows.py`
— ran against the side venv.

Results :

| Suite | Under 0.109 | Under 0.115 |
|---|---|---|
| All hardening tests (74) | 74 / 74 pass | 74 / 74 pass |
| Import smoke (13 modules) | n/a | 13 / 13 ok |
| OAuth2 `/auth/token` POST | pass | pass |

The TODO comment in `requirements.txt` listed "Pydantic v2 lifecycle,
route signatures, OAuth2 flows" as risky. The actual breaks found are
much narrower than the comment feared.

## The breaks actually found (concrete)

### Break 1 — `status_code=204` + default response class

**Single occurrence.** `api/routes/projects.py:266` :

```python
@router.delete("/{project_id}", status_code=204, dependencies=[])
async def delete_project_endpoint(...) -> None:
    ...
```

Under FastAPI 0.115 this throws at route-registration time :

```
File "fastapi/routing.py", line 507, in __init__
    assert is_body_allowed_for_status_code(
AssertionError: Status code 204 must not have a response body
```

FastAPI 0.115 now refuses to mix a 204 status with the default
`JSONResponse` response class (which always carries a body). The route
function returns `None` so the intent is correct ; only the wiring
needs adjustment.

**Fix** — one line :

```diff
+from fastapi import Response
-@router.delete("/{project_id}", status_code=204, dependencies=[])
+@router.delete("/{project_id}", status_code=204, response_class=Response, dependencies=[])
```

`fastapi.Response` (re-export of `starlette.responses.Response`) is the
body-less base response class. With `response_class=Response`, the
204 + no-body contract is consistent.

### No other breaks under the test suite we run

Smoke covers : `config.settings`, `api.auth`, `api.token_utils`,
`api._deps`, `api.jwt_v2`, `core._logging_helpers`, `api.routes.auth`,
`api.routes.system_readiness`, `api.routes.economic`, `api.routes.business`,
`models.project`, `core.agent_factory`, `api.main`. All import clean.

Tests we ran against the new stack : `test_p1_hardening` (19),
`test_jwt_v2` (30), `test_auth_routes_v2_flag` (8),
`test_logging_helpers` (11), `test_architecture_size_gate` (2),
`test_no_new_silent_swallows` (4). Total 74 ; all pass.

## What stayed compatible (and why the TODO was conservative)

The audit TODO worried about three surfaces. Reality :

| Surface | Audit fear | Result |
|---|---|---|
| Pydantic v2 lifecycle | `class Config` → `model_config` migration | Pydantic 2.13 still tolerates `class Config` with a DeprecationWarning. The 4 sites (`core/agent_factory.py:43`, `models/project.py:64,73,103`) keep working. Migration is a quality follow-up, NOT a blocker. |
| Route signatures | `Annotated[...]` enforced | FastAPI 0.115 still accepts the `param: T = Depends(...)` syntax. The `Annotated[T, Depends(...)]` form is recommended but not required. |
| OAuth2 flows | `OAuth2PasswordRequestForm = Depends()` rejected | Still works exactly as in 0.109. Verified with an end-to-end `/auth/token` POST. |

The single real break is the 204 strict-body check, which is one line in
one file.

## Pydantic v1 `class Config` sites (deprecation, not blocker)

For completeness, the 4 sites that emit `PydanticDeprecatedSince20`
warnings under both 0.109 and 0.115. Migrate when convenient :

| File:line | Current | Target |
|---|---|---|
| `core/agent_factory.py:43` | `class Config: extra = "allow"` | `model_config = ConfigDict(extra="allow")` |
| `models/project.py:64` | `class Config: extra = "allow"` | same |
| `models/project.py:73` | `class Config: extra = "allow"` | same |
| `models/project.py:103` | `class Config: json_encoders = {UUID: str, datetime: lambda v: v.isoformat()}` | replace with `@field_serializer` decorators (slightly more involved) |

The first three are 2-line diffs. The fourth needs converting two
`json_encoders` entries to `@field_serializer("id")` / `@field_serializer("created_at")`
decorators on the model. Total effort : ~30 minutes including tests.

## Migration PR checklist

When the team is ready to execute :

1. [ ] Branch from `main` after the latest hardening commits are in.
2. [ ] Bump `requirements.txt` :
       ```
       fastapi==0.115.6
       # Starlette is pulled transitively at 0.41.x ; pin explicitly for
       # supply chain visibility :
       starlette==0.41.3
       ```
3. [ ] Apply the one-line fix to `api/routes/projects.py:266`
       (see "Break 1" above). Add `from fastapi import Response` to the
       imports of that file.
4. [ ] Regenerate `requirements.lock` :
       `docker build -f docker/Dockerfile -t beamax-master-bea:bumpcheck . && \
        docker run --rm beamax-master-bea:bumpcheck pip freeze > requirements.lock`
5. [ ] Re-run the smoke harness in the new env :
       `python scripts/c4_fastapi_115_smoke.py`
6. [ ] Run the test suite. Expected : same green as before the bump.
7. [ ] Refresh the `quality/pip-audit-baseline.json` : the two
       deferred Starlette CVEs (CVE-2024-47874, CVE-2025-54121) should
       leave the report. Remove them from `ignored_ids` and drop the
       matching TODO rows from `requirements.txt`.
8. [ ] Update the `requirements.txt` TODO comment block lines 17-20 —
       delete the deferred-bump TODO ; replace with a short
       "bumped 2026-XX-XX, see PR #N" note.
9. [ ] Smoke staging for the same 24-48h window used for Mo2 prep
       (audit follow-up).

## Optional follow-up (not in this PR)

* Migrate the 4 `class Config:` sites to `model_config = ConfigDict(...)`
  to clear `PydanticDeprecatedSince20` warnings.
* Adopt the `Annotated[T, Depends(...)]` style in new routes (the
  existing routes keep working).
* Consider bumping `python-multipart` to >=0.0.20 in the lockfile,
  which is what FastAPI 0.115 recommends.

## Estimated effort

Based on the actual reconnaissance done in this prep :

| Step | Effort |
|---|---|
| The bump itself (`requirements.txt` + `requirements.lock`) | 15 min |
| The 1-line projects.py fix + matching unit test | 15 min |
| Pip-audit baseline cleanup | 10 min |
| Test suite run + investigate any new flake | 30 min |
| Staging soak | 24-48 h calendar time, ~30 min hands-on |
| **Total** | **~1 hour of hands-on engineering** |

This is much smaller than the original audit TODO suggested ("À planifier
en PR dédiée"). The bump is mostly a documentation + lockfile change
plus a 1-line code fix. The risk surface that worried the audit
(Pydantic v2, OAuth2) turned out to be a non-issue under the actual
pinned versions.
