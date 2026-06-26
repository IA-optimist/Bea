# Private Beta Runbook

PRIVATE_BETA_READY: true for 5-10 technical testers under supervision.
PUBLIC_BETA_READY: false.

## Before Inviting Testers

1. Run `python scripts/check_docs_truth.py`.
2. Run `python scripts/validate_local.py --quick`.
3. Run `python scripts/check_client_v1_usage.py`.
4. Run `python scripts/audit_memory_store.py --dry-run --privacy-scan --json`.
5. Confirm Qdrant live memory has no private items, or record cleanup as
   HUMAN_REQUIRED.
6. Confirm tester tokens are unique and not committed.
7. Confirm self-improvement is disabled by default.

## Tester Rules To Communicate

- Use toy data only.
- Do not provide real secrets.
- Do not provide private, medical, financial, customer, or regulated data.
- Report incidents with redacted logs.
- Treat Android APK as experimental unless the current validation checklist is
  complete.

## Stop Conditions

- Any secret appears in logs, memory, issue text, or screenshots.
- Qdrant privacy scan finds private data.
- A dangerous action bypasses policy gates.
- Authentication or principal binding fails.
- Testers start using real sensitive data.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate exposed or historical secrets.
- HUMAN_REQUIRED: cleanup Qdrant private items.
- HUMAN_REQUIRED: revoke affected tester tokens.
- HUMAN_REQUIRED: document incident timeline in an issue or private report.
