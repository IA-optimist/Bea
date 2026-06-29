# Agentic Runtime

The agentic runtime is the controlled Agent Computer Interface for Bea agents.
It is designed around structured requests and structured results instead of
free-form tool calls.

## Core Objects

- `ActionRequest`: required `mission_id`, `agent_id`, `action_type`, `realm`,
  `payload`, optional `idempotency_key`, and timestamp.
- `ActionResult`: enum status, bounded output, typed errors, artifacts,
  `audit_ref`, duration, and redaction before return.
- `CommandPolicy`: allowed/denied actions, allowed realms, allowed/denied paths,
  runtime/output limits, and risk approval threshold.
- `ACIActionRegistry`: deny-by-default action registry with required
  capabilities per action.

## Enforcement Order

1. Action must be registered.
2. Action must be allowed by `CommandPolicy`.
3. Realm must be allowed when `allowed_realms` is configured.
4. Agent capabilities must satisfy the action registration.
5. File writes must be inside explicitly allowed paths.
6. Sensitive paths require explicit path allow.
7. Risk above the approval threshold returns `approval_required`.
8. Handler result is redacted and bounded.
9. Audit event is emitted with redacted payload summary.

## Implemented Handlers

| Action | Handler | Status |
| --- | --- | --- |
| `apply_patch` | `apply_patch_handler` | Minimal safe update-patch implementation |
| `write_report` | `write_report_handler` | Implemented with redaction |
| Read/search/test/lint/typecheck/security scan/git actions | Stub handlers | Registered but not implemented as runtime handlers |

## Patch Handler Guarantees

- Blocks empty patches.
- Blocks patches larger than 200 KB.
- Blocks path traversal and absolute patch paths.
- Blocks target/path mismatch.
- Requires the target file to exist.
- Requires context to match before modifying.
- Returns changed files, added/removed line counts, and before/after SHA-256.

## Audit Event

Each runtime decision can emit:

- `audit_ref`
- `who`
- `what`
- `mission_id`
- `action`
- `allowed`
- `reason`
- `timestamp`
- `risk`
- redacted `payload_summary`

When an audit sink is configured, `ActionResult.audit_ref` points to the
corresponding audit event.

Forbidden in audit/log/output: tokens, API keys, authorization headers,
passwords, private keys, cookies, connection strings, and seed phrases.
