# Feedback Guide

Use this guide for Private Beta 0.1 feedback.

## Include

- Commit SHA.
- Operating system.
- Command or UI path.
- Expected result.
- Actual result.
- Redacted logs.
- Whether Android, API, memory, auth, docs, or provider behavior was involved.

## Do Not Include

- Real secrets.
- `.env` contents.
- Real private, medical, financial, customer, or regulated data.
- Screenshots containing tokens or personal data.

## Priority Hints

| Priority | Examples |
|---|---|
| P0 | Secret exposure, auth bypass, dangerous action bypass, private memory leak |
| P1 | Mission corruption, data loss, Android mission UI blocker |
| P2 | Documentation mismatch, confusing error, provider timeout |

## HUMAN_REQUIRED

- HUMAN_REQUIRED: owner triages P0 reports before inviting more testers.
