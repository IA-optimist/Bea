# EvidenceGate — Anti-Hallucination Reference

## Why Evidence Is Required

AI agents can hallucinate — claiming a vulnerability exists when it doesn't. `EvidenceGate` prevents this by requiring attached evidence before any `Claim` can be `VERIFIED`.

**Rule**: No evidence → claim is `UNVERIFIED` or `REJECTED`. Never `VERIFIED`.

## EvidenceType

| Type | When to Use |
|------|-------------|
| `FILE_LOCATION` | Points to a specific file/line in the codebase |
| `CODE_SNIPPET` | A code excerpt showing the vulnerability pattern |
| `TEST_OUTPUT` | Output from a test run (pytest, bandit, etc.) |
| `TOOL_OUTPUT` | Output from a scanner (pip-audit, etc.) |
| `DEPENDENCY_REPORT` | pip-audit or similar dependency check output |
| `SECRET_SCAN_RESULT` | Redacted secret scan output |
| `CONFIG_VALUE` | A specific config key/value |
| `HTTP_OBSERVATION` | HTTP response headers or body (authorized targets only) |
| `USER_PROVIDED_AUTHORIZATION` | Written authorization document |

## Claim → Evidence → Status Workflow

```
Claim created (status=UNVERIFIED)
    ↓
EvidenceGate.validate_claim(claim)
    ↓
  ┌─ Has evidence_refs?
  │    No  → VULNERABILITY_EXISTS: UNVERIFIED
  │          TEST_PASSED: REJECTED
  │          SCOPE_AUTHORIZED: REJECTED
  │    Yes → evidence_refs exist in gate?
  │          No  → REJECTED
  │          Yes → check evidence type matches requirement
  │                FIX_VALID needs CODE_SNIPPET or TEST_OUTPUT
  │                TEST_PASSED needs TEST_OUTPUT
  │                SCOPE_AUTHORIZED needs USER_PROVIDED_AUTHORIZATION
  └─ All checks pass → VERIFIED
```

## Claim Types

| Type | Requires Evidence | Without Evidence |
|------|-------------------|------------------|
| `VULNERABILITY_EXISTS` | Recommended | UNVERIFIED (not rejected — pattern match may be valid) |
| `VULNERABILITY_ABSENT` | Recommended | UNVERIFIED |
| `TEST_PASSED` | `TEST_OUTPUT` required | REJECTED |
| `FIX_VALID` | `CODE_SNIPPET` or `TEST_OUTPUT` | UNVERIFIED |
| `RISK_ASSESSMENT` | Recommended | UNVERIFIED |
| `SCOPE_AUTHORIZED` | `USER_PROVIDED_AUTHORIZATION` required | REJECTED |

## Example

```python
gate = EvidenceGate()

# Attach evidence
ev = Evidence(
    evidence_type=EvidenceType.CODE_SNIPPET,
    source="repo_map",
    content_summary="Line 42: query = 'SELECT * FROM users WHERE id = ' + user_id",
    confidence=0.95,
    file="api/routes.py",
    line_start=42,
    function="get_user",
)
gate.attach_evidence(ev)

# Make claim
claim = Claim(
    claim_type=ClaimType.VULNERABILITY_EXISTS,
    content="SQL injection in get_user via string concatenation",
    confidence=0.95,
    evidence_refs=[ev.evidence_id],
)
result = gate.validate_claim(claim)
# result.status == ClaimStatus.VERIFIED
```

## Secret Redaction

`Evidence.content_summary` auto-redacts API keys, Bearer tokens, and bea-tokens. Raw secrets should **never** appear in `content_summary` — use `raw_ref` (a file path, not content) for referencing sensitive locations.
