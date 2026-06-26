# PR Cleanup Baseline Report

Generated: 2026-06-26
Branch: chore/github-pr-cleanup

## Repo State

- **main commit**: `a59b034ad93c0ff71ed1b6692eb6d045a782b3c8`
- **Open PRs**: 21
- **Open issues**: 5
- **gh CLI access**: ✅ Yes (`repo` scope via IA-optimist account)
- **Permissions**: ✅ merge + close + comment + label

## PR Inventory

| # | Title | Author | Age (from 2026-06-26) | Branch | Mergeable | Draft | Category | Initial Decision |
|---|-------|--------|-----------------------|--------|-----------|-------|----------|-----------------|
| #115 | [codex] add bea upgrade tooling | IA-optimist | 1d | codex/bea-upgrade-direct-20260626 | MERGEABLE | ✅ DRAFT | UNKNOWN/DRAFT | KEEP_OPEN — DRAFT, 41 files, not ready |
| #112 | fix(eval): stabilize bea_eval and enforce completion truth gates | IA-optimist | 3d | claude/stabilize-bea-eval-and-completion-truth-gates | CONFLICTING | ❌ | PRIVATE_BETA_GATE | NEEDS_FIX — rebase required, high value |
| #95 | deps(py): bump the runtime group (6 packages) | dependabot | 4d | dependabot/pip/runtime-7b8c6f63c4 | UNKNOWN | ❌ | PYTHON_DEPENDENCY | NEEDS_OWNER_DECISION — fastapi/uvicorn/pydantic/structlog major |
| #94 | docs(flutter): validate v3 migration + APK rebuild | IA-optimist | 5d | claude/flutter-v3-apk-validation | CONFLICTING | ❌ | FLUTTER_APK / DOCS_TRUTH | NEEDS_FIX — rebase required |
| #93 | fix(scripts): Windows Unicode safety + --dry-run | IA-optimist | 5d | claude/alpha-environment-polish | CONFLICTING | ❌ | FALSE_COMPLETED_PREVENTION | NEEDS_FIX — rebase required |
| #68 | Fix remaining Dependabot dependency alerts | IA-optimist | 9d | fix/dependabot-alerts | CONFLICTING | ❌ | LEGACY_JARVISMAX | CLOSE — touches mobile/+orchestrate-mobile/ paths not in main |
| #60 | deps(py): bump test-tooling group (4 packages) | dependabot | 4d | dependabot/pip/test-tooling-0c75e36662 | MERGEABLE | ❌ | PYTHON_DEPENDENCY | MERGE — safe pytest/pytest-cov/pytest-mock/mypy patches |
| #39 | deps(flutter): bump flutter_secure_storage 9→10.3.1 /beamax_app | dependabot | 19d | dependabot/pub/beamax_app/flutter_secure_storage-10.3.1 | UNKNOWN | ❌ | FLUTTER_DEPENDENCY | NEEDS_FLUTTER_VALIDATION — major bump on credential storage |
| #38 | deps(flutter): bump flutter_local_notifications 17→21 /beamax_app | dependabot | 19d | dependabot/pub/beamax_app/flutter_local_notifications-21.0.0 | UNKNOWN | ❌ | FLUTTER_DEPENDENCY | NEEDS_FLUTTER_VALIDATION — major bump |
| #37 | deps(flutter): bump web_socket_channel 2→3 /beamax_app | dependabot | 19d | dependabot/pub/beamax_app/web_socket_channel-3.0.3 | UNKNOWN | ❌ | FLUTTER_DEPENDENCY | NEEDS_FLUTTER_VALIDATION — major bump |
| #36 | deps(py): Bump stripe 8.0.0→15.2.1 | dependabot | 9d | dependabot/pip/stripe-15.2.0 | UNKNOWN | ❌ | PYTHON_DEPENDENCY | NEEDS_OWNER_DECISION — 7 major version jump |
| #27 | docs(security): audit dépendances pip-audit + P0/P1/P2 | IA-optimist | 25d | chore/p0-dependency-audit | CONFLICTING | ❌ | OLD_DOCS | CLOSE — historical audit from 2026-06-01, requirements.txt superseded |
| #26 | docs: réaligne README + plan P0/P1/P2 post-audit | IA-optimist | 25d | docs/p0-readme-realignment | CONFLICTING | ❌ | OLD_DOCS | CLOSE — README already updated in main, plan superseded |
| #24 | deps(flutter): bump flutter_secure_storage /jarvismax_app | dependabot | 32d | dependabot/pub/jarvismax_app/flutter_secure_storage-10.3.0 | UNKNOWN | ❌ | LEGACY_JARVISMAX | CLOSE — jarvismax_app removed from main |
| #23 | deps(flutter): bump web_socket_channel /jarvismax_app | dependabot | 32d | dependabot/pub/jarvismax_app/web_socket_channel-3.0.3 | UNKNOWN | ❌ | LEGACY_JARVISMAX | CLOSE — jarvismax_app removed from main |
| #22 | deps(py): Update llama-index-embeddings-openai >=0.6.0 | dependabot | 9d | dependabot/pip/llama-index-embeddings-openai-gte-0.6.0 | UNKNOWN | ❌ | PYTHON_DEPENDENCY | MERGE — orchestrate-cli only, safe floor bump |
| #21 | deps(py): Bump prometheus-client 0.19→0.25 | dependabot | 9d | dependabot/pip/prometheus-client-0.25.0 | UNKNOWN | ❌ | PYTHON_DEPENDENCY | MERGE — monitoring only, safe minor bump |
| #20 | deps(ci): Bump codecov/codecov-action 3→7.0.0 | dependabot | 6d | dependabot/github_actions/codecov/codecov-action-6.0.1 | MERGEABLE | ❌ | CI_DEPENDENCY | MERGE — pinned SHA, continue-on-error, safe |
| #19 | deps(ci): Bump softprops/action-gh-release 2→3.0.1 | dependabot | 6d | dependabot/github_actions/softprops/action-gh-release-3.0.0 | UNKNOWN | ❌ | CI_DEPENDENCY | MERGE — pinned SHA, tag-only, safe |
| #18 | deps(ci): Bump docker/setup-buildx-action 3.12→4.1.0 | dependabot | 6d | dependabot/github_actions/docker/setup-buildx-action-4.1.0 | MERGEABLE | ❌ | CI_DEPENDENCY | MERGE — pinned SHA, CI only, safe |
| #10 | deps(flutter): bump connectivity_plus /jarvismax_app | dependabot | 38d | dependabot/pub/jarvismax_app/connectivity_plus-7.1.1 | UNKNOWN | ❌ | LEGACY_JARVISMAX | CLOSE — jarvismax_app removed from main |

## Summary of Initial Decisions

| Decision | Count | PRs |
|----------|-------|-----|
| MERGE (safe) | 6 | #18, #19, #20, #21, #22, #60 |
| CLOSE (legacy/stale) | 6 | #10, #23, #24, #26, #27, #68 |
| NEEDS_FIX (rebase) | 3 | #93, #94, #112 |
| NEEDS_OWNER_DECISION | 2 | #36, #95 |
| NEEDS_FLUTTER_VALIDATION | 3 | #37, #38, #39 |
| KEEP_OPEN (DRAFT) | 1 | #115 |

## Notes

- `jarvismax_app/` directory confirmed absent from main (verified via GitHub API tree)
- `mobile/` and `orchestrate-mobile/` directories confirmed absent from main (PR #68 targets non-existent paths)
- PR #112 is the highest-priority PRIVATE_BETA_GATE PR — completion truth gates + bea_eval --isolated
- PRs #37/38/39 target `beamax_app/` which is active; major version bumps require `flutter test` + `flutter build apk`
- PR #95 includes uvicorn 0.42→0.49 (7 minor versions) and fastapi 0.137→0.138 — needs validation in test env
- PR #36 is stripe 8→15 (7 major versions) — high-risk API compatibility change
