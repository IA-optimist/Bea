# Known Limitations

PUBLIC_BETA_READY: false

## Runtime

| Limitation | Current truth |
|---|---|
| Self-improvement | Disabled by default; keep it opt-in with operator review |
| Dangerous actions | Must be gated or out of scope |
| Session store | `RedisSessionStore` for multi-process or multi-worker; `InMemorySessionStore` only for local single-process testing |
| Multi-tenant use | Out of scope for Private Beta 0.1 |

## Memory

| Limitation | Current truth |
|---|---|
| Qdrant live memory | 2026-06-26 privacy scan found 1 private item; cleanup required |
| Public seed | `seed_bea_memory.py --report --profile public` passed with 8 public-safe items |
| Sensitive data | Testers must not use real private, medical, financial, customer, or regulated data |

## API And Mobile

| Limitation | Current truth |
|---|---|
| Flutter `/api/v1` usage | 0 active calls by `check_client_v1_usage.py` |
| Server v1 compatibility | May remain for deliberate rollback compatibility; do not assume removal is safe without review |
| Android APK | Partially validated only; mission UI and offline/network-failure are HUMAN_REQUIRED |

## Experimental Or Partial Areas

- HexStrike and offensive/cyber workflows.
- Business automation.
- Venture workflows.
- Multimodal and voice.
- Browser automation.
- SaaS deployment for untrusted external users.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: secret rotation proof.
- HUMAN_REQUIRED: Qdrant cleanup proof.
- HUMAN_REQUIRED: Android physical-device mission UI proof.
- HUMAN_REQUIRED: Android offline/network-failure proof.
