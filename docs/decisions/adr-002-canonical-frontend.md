# ADR-002 — Canonical Frontend Surface

## Status
Accepted

## Context
The Bea platform is primarily API-driven. The visible user surface today is a
single-page web application (`frontend/`). The consolidation roadmap required a
clear decision about which frontend stack is canonical, in order to stop
maintaining duplicate surfaces and conflicting mobile strategies.

## Decision

- **Canonical surface**: the web SPA in `frontend/` is the single supported
  end-user interface.
- **Mobile access**: mobile clients must consume the public API (`/api/v1`)
  directly or wrap the web SPA in a thin WebView container.
- **No new React Native or Flutter mobile clients** will be added to this repo.
  If a native mobile experience becomes a hard requirement later, Flutter is the
  preferred technology (per ADR-001 interface strategy), but its implementation
  must live in a dedicated `bea-mobile` repository.

## Consequences

- We stop duplicating feature work across multiple frontends.
- Auth/security fixes only need to be applied in `frontend/src` and the API
  middleware layers.
- The web SPA must remain responsive and PWA-ready to cover mobile use cases.

## References
- `docs/decisions/adr-001-canonical-interfaces.md`
- `docs/STATUS.md`
