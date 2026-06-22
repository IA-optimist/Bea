# Public Beta Memory Policy

## Goal

This document defines the rules for preparing a **clean, public-safe memory seed**
for Béa's Developer Preview / limited public beta.

The local memory store of individual developers may contain private jokes,
personal data, secrets, and duplicates. **None of that must ever ship in a
public release.**

## What is allowed in public memory

Only **neutral project facts** are acceptable:

- Architecture decisions (e.g., "api/routes/v1.py is the canonical v1 facade")
- Verified repo facts (e.g., "HexStrike v2 must stay out of core/")
- Operational risk/policy rules (e.g., "Unsigned patches must never be PROMOTEd")
- Test maps (e.g., module ↔ test file links)
- Generic skills and procedures with no personal context

## What is strictly forbidden

| Category | Examples | Detection |
|----------|----------|-----------|
| **Secrets** | API keys, tokens, passwords, OAuth credentials | `audit_memory_store.py --privacy-scan` (token regex) |
| **Emails** | Personal or developer email addresses | `audit_memory_store.py --privacy-scan` (email regex) |
| **Private jokes** | Tags containing `private_joke` | `audit_memory_store.py --privacy-scan` (tag check) |
| **Personal fun facts** | Tags containing `personal` or `fun_fact_personal` | `audit_memory_store.py --privacy-scan` (tag check) |
| **Personal data** | Names, phone numbers, addresses, personal preferences | Manual review + tag check |
| **Private sources** | `source` field containing `private`, `user_private`, `personal_note` | `audit_memory_store.py --privacy-scan` (source keyword) |

## Pre-release audit procedure

Before any public beta release:

1. **Run the privacy scan (non-destructive):**

   ```bash
   python scripts/audit_memory_store.py --dry-run --privacy-scan --json
   ```

2. **Check for duplicates:**

   ```bash
   python scripts/audit_memory_store.py --dry-run --sample-duplicates 20 --json
   ```

3. **Verify the seed script:**

   ```bash
   python scripts/seed_bea_memory.py --report
   ```

   This prints a verdict:
   - `public_safe: true/false`
   - `has_private_joke: true/false`
   - `has_personal_data: true/false`
   - `has_secret: true/false`

4. **If `public_safe` is false**, review the flagged items and remove them
   from the seed before release. **Never** use `--apply` on a production store.

## Backup procedure (for future destructive PR)

`--apply` is **always refused** in the current PR. When a future PR introduces
destructive cleanup, it must:

1. Create a full backup of `operational_memory.db` before any modification.
2. Require an explicit `--backup-path` flag pointing to the backup location.
3. Refuse to run if the backup file does not exist or is empty.
4. Log every deletion for audit trail.

## Duplicate classification

Duplicates detected by the audit are classified as:

| Classification | Meaning |
|----------------|---------|
| `SAFE_MERGE_CANDIDATE` | Items with same title+source that could be merged after review |
| `REVIEW_REQUIRED` | Default — a human must verify before any action |
| `DO_NOT_MERGE` | Items that look similar but have different semantics |

**No duplicate is ever auto-deleted.** All merges require manual review.

## Command reference

```bash
# Full non-destructive audit with privacy scan
python scripts/audit_memory_store.py --dry-run --privacy-scan --json

# Privacy scan with limited samples
python scripts/audit_memory_store.py --privacy-scan --sample-private 10 --json

# Duplicate sampling only
python scripts/audit_memory_store.py --dry-run --sample-duplicates 20 --json

# --apply is always refused
python scripts/audit_memory_store.py --apply
# → ERROR: --apply is disabled in this PR.
```
