# Béa — Privacy for Testers

> Private beta only. Last updated 2026-06-24.

## Our commitment

During the private beta, we will:

- Never ask for your production passwords or API keys.
- Never require you to submit personal data to test the system.
- Keep beta communications in a private channel.
- Treat security reports confidentially.

## Your responsibilities

As a tester, you agree to:

- **Do not put secrets into Béa.** This includes passwords, API keys, tokens, bearer tokens, credentials, cookies, private keys, or database connection strings.
- **Do not put personal data into Béa.** Avoid names, emails, addresses, phone numbers, credit-card numbers, SSNs, or customer data.
- **Run in an isolated environment.** Use a local machine or a dedicated VM/container, not a production server.
- **Do not share screenshots, logs, or recordings publicly** without operator approval.
- **Redact before reporting.** Replace tokens, IPs, emails, and identifiers with `REDACTED` in bug reports.

## What happens to data you submit

- Mission inputs may be stored in memory (Qdrant/SQLite) for retrieval.
- Logs are written locally on the machine running Béa.
- The operator running the beta instance controls data retention.
- We do not operate a shared cloud backend for this beta.

## Memory hygiene

Béa ships a public-safe memory seed and an audit script:

```bash
python scripts/seed_bea_memory.py --report --profile public
python scripts/audit_memory_store.py --dry-run --privacy-scan --json
```

These scripts ensure that seeded knowledge contains no private items, API keys, or PII.

## How to report a privacy concern

Use `.github/ISSUE_TEMPLATE/security_report.md` and send it privately to the operator.  
Do **not** open a public issue.

## Legal notice

This is an experimental private beta. There is no SLA, no warranty, and no guarantee of data retention or confidentiality beyond the commitments above. If you need a DPA or formal review, contact the operator before participating.
