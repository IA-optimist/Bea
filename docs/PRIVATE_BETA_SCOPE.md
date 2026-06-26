# Private Beta Scope 0.1

PRIVATE_BETA_READY: true for 5-10 technical testers under supervision.
PUBLIC_BETA_READY: false.

Bea is a Developer Preview / Private Beta 0.1. This scope does not authorize an
open beta.

## Allowed Testers

- 5-10 technical testers maximum.
- Comfortable with Python, logs, Docker, and GitHub issues.
- Able to avoid real secrets and sensitive real data.
- Able to report failures with redacted logs.

## Allowed Surfaces

| Surface | Status |
|---|---|
| Local API on `localhost` | Allowed for supervised testing |
| Web cockpit | Allowed for basic control only |
| Android APK | Experimental companion surface; API direct usage must remain available |
| OpenRouter/Ollama | Allowed with tester-owned credentials or owner-provisioned tokens |
| Qdrant memory | Allowed only after cleanup or with public-safe seeded data |

## Out Of Scope

- Open beta.
- Multi-tenant use.
- Unsupervised self-improvement.
- Dangerous actions without gates.
- Real secrets in prompts, logs, issues, or memory.
- Real private, medical, financial, customer, or regulated data.
- HexStrike or offensive/cyber testing.
- SaaS deployment for untrusted external users.

## Exit Criteria Before Open Beta

- [ ] Qdrant privacy scan proves 0 private live items.
- [ ] Historical/shared secret rotation is proved by the owner.
- [ ] Android mission UI is validated on a physical device.
- [ ] Android offline/network-failure behavior is validated on a physical
  device.
- [ ] `RedisSessionStore` is used for multi-process or multi-worker testing.
- [ ] Full validation and docs truth gate pass.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: tester token creation and revocation process.
- HUMAN_REQUIRED: secret rotation proof.
- HUMAN_REQUIRED: live memory cleanup proof.
- HUMAN_REQUIRED: Android physical-device proof.
