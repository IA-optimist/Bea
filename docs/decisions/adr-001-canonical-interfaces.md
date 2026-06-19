# ADR-001 - Canonical interfaces

Status: Accepted
Date: 2026-06-18

## Context

Bea has three interface layers:

- `beamax_app/` - Flutter Android app, documented as the canonical mobile app.
- `frontend/` - React/Vite cockpit. Wired to the current API, but still carries mixed v2/v3 route debt.
- `mobile/` - React Native/Expo app. It is not wired to the current API contract and is secondary to Flutter.

This creates ambiguity for release ownership and increases the risk of shipping stale UIs.

## Decision

1. `beamax_app/` remains the canonical mobile interface.
2. `frontend/` is treated as wired-but-secondary: usable, but still allowed to carry legacy route debt until it is cleaned.
3. `mobile/` is treated as scaffolding/legacy until a maintainer explicitly reassigns it as canonical.
4. CI/release scripts must not claim that `frontend/` or `mobile/` are production-ready unless the routing debt is explicitly cleared.

## Consequences

- Positive:
  - One canonical mobile target.
  - Less confusion for deployment and QA.
  - Clearer maintenance boundary.
- Negative:
  - React/React Native UI work must be migrated intentionally before being reused.
  - Some useful UI components may be temporarily underused.

## Follow-up

- Keep pruning stale route calls in `frontend/src/api/client.ts`.
- Add a small CI gate that prevents stale `/system/status` calls from remaining in the cockpit client.
