# Béa Doctor

`bea doctor` is a fail-closed readiness gate for the repo.

It reports three tiers:

- `Local dev`: basic repo health for day-to-day work.
- `Private beta`: whether the project is safe for a small supervised test group.
- `Public beta`: whether the project has the proofs needed for wider exposure.

What it checks:

- beta-status truth in the main docs;
- whether self-improvement is off by default;
- whether dangerous tools are visibly gated;
- whether human approval paths exist;
- whether a safe session/memory store is present;
- whether beta/prod session storage is explicitly configured for Redis;
- whether memory privacy, sandboxing, channel access control, and secret hygiene have visible evidence;
- whether validation scripts and critic rerun invariants are present.

Recommended session-store env vars:

- `BEA_SESSION_STORE=memory` for local dev
- `BEA_SESSION_STORE=redis` plus `BEA_REDIS_URL=redis://...` for beta/prod

What it does not do:

- it does not make the project beta-ready;
- it does not run destructive checks;
- it does not treat a missing proof as a PASS;
- it does not override existing security gates.

Public beta can remain `FAIL` even when unit tests pass. That is expected when a critical gate is missing or unproved.
