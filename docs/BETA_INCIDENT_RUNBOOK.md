# Beta Incident Runbook

Use this runbook for Private Beta 0.1 incidents.

## Stop Immediately

Stop testing if any of these happen:

- A real secret appears in logs, output, screenshots, memory, or an issue.
- A private memory item is visible to a tester.
- A dangerous action runs without a gate.
- Auth principal binding looks wrong.
- A tester used real private, medical, financial, customer, or regulated data.

## First Response

1. Revoke affected tester tokens.
2. Stop the affected service if exposure is ongoing.
3. Preserve redacted logs.
4. Record commit SHA, command, tester, and timestamp.
5. Rotate exposed or historical/shared secrets as needed.
6. Run `python scripts/audit_memory_store.py --dry-run --privacy-scan --json`.
7. Clean Qdrant live memory if private items are found.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: token revocation.
- HUMAN_REQUIRED: secret rotation.
- HUMAN_REQUIRED: memory cleanup.
- HUMAN_REQUIRED: incident report reviewed by the owner.
