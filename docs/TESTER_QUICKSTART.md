# Tester Quickstart

Bea Private Beta 0.1 is for 5-10 technical testers under supervision.
PUBLIC_BETA_READY: false.

## Before You Start

- Use toy data only.
- Do not paste real secrets, passwords, API keys, private data, medical data,
  financial data, customer data, or regulated data.
- Keep self-improvement disabled unless the owner explicitly asks for a
  supervised test.
- Treat Android APK support as partial unless the current validation checklist
  is complete.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
copy .env.example .env
python scripts/validate_local.py --quick
python scripts/run_api_local.py
```

## Suggested First Checks

```bash
python scripts/check_client_v1_usage.py
python scripts/check_docs_truth.py
python scripts/seed_bea_memory.py --report --profile public
```

## Reporting Feedback

Use [FEEDBACK_GUIDE.md](FEEDBACK_GUIDE.md). Always redact logs.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: get a unique tester token from the owner.
- HUMAN_REQUIRED: report any accidental secret exposure immediately.
