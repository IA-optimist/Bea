# Beta Access Setup

PRIVATE_BETA_READY: true for 5-10 technical testers under supervision.
PUBLIC_BETA_READY: false.

## Owner Checklist

- [ ] Confirm docs truth gate passes.
- [ ] Confirm quick validation passes.
- [ ] Confirm a Qdrant privacy report shows no private live items, or record cleanup as HUMAN_REQUIRED.
- [ ] Rotate historical/shared secrets if not already proved outside the repo.
- [ ] Create one token per tester.
- [ ] Send safety rules before access.
- [ ] Confirm `RedisSessionStore` before multi-process or multi-worker use.

## Token Rules

- Do not commit tester tokens.
- Do not share one token across testers.
- Revoke tokens after the test window.
- Rotate immediately if a token is pasted into logs, issues, screenshots, or
  chat.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: secret rotation proof.
- HUMAN_REQUIRED: tester token creation and revocation.
- HUMAN_REQUIRED: Qdrant cleanup proof.
