# Release Process — Béa

## Prerequisites

- All PRs for the release merged to main
- `ruff check .` clean
- `pytest` green (critical tests)
- `scripts/validate_local.py --quick` all gates passed
- `scripts/bea_eval.py --json` 25/25
- `scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json` passed
- `scripts/release_check.py --json` → `overall_status: "pass"`
- No secrets in any committed file
- `.env.example` reviewed: only placeholders, no real keys

## Pre-release checklist

```bash
# 1. Release check (presence + no-secrets + no production-ready claims)
python scripts/release_check.py --json

# 2. Validate local
python scripts/validate_local.py --quick

# 3. bea_eval
python scripts/bea_eval.py --json

# 4. Smoke (fixture, no LLM required)
python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json

# 5. Grep for secrets in release files
grep -rE "sk-|OPENROUTER_API_KEY=[^<R]|Bearer [a-zA-Z0-9]" \
  .env.example CHANGELOG.md RELEASE_NOTES.md docs/ || echo "clean"
```

## Create VERSION and tag (manual)

```bash
# Ensure VERSION file matches intended release
cat VERSION

# Commit if needed
git add VERSION CHANGELOG.md RELEASE_NOTES.md
git commit -m "chore: bump version to $(cat VERSION)"

# Tag (annotated, not lightweight)
git tag -a "v$(cat VERSION)" -m "Developer Preview — not production ready"
git push origin "v$(cat VERSION)"
```

## Publish release (manual via GitHub UI)

1. Go to https://github.com/IA-optimist/Bea/releases/new
2. Select the tag created above
3. Title: `Béa $(cat VERSION) — Developer Preview`
4. Body: paste `RELEASE_NOTES.md` content
5. Check **"Set as a pre-release"**
6. Do NOT check "Set as the latest release"
7. Click **Publish release**

## Rollback

If a critical issue is found after release:

1. Open a revert PR for the problematic commit
2. Tag a patch: e.g. `v0.1.1-dev-preview`
3. Flutter: reinstall previous APK — v1 server endpoints are preserved until 2026-10-01
4. Notify beta testers via Telegram or GitHub issue

## Rules

- Never auto-publish releases via CI without human review
- Never tag main without running the full pre-release checklist
- Developer Preview tags must always include `-dev-preview` suffix
- Never use `--force` to push a tag
