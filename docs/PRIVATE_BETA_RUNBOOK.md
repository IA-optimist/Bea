# Béa — Private Beta Runbook

> For the operator running the private beta. Read this before inviting testers.

## Pre-flight checklist

Run these commands from the repo root on the beta branch:

```bash
git checkout beta/private-readiness-kilo-kimi
git pull origin beta/private-readiness-kilo-kimi

python scripts/private_beta_gate.py --json
# Confirm: ready_for_private_beta == true

ruff check .
# Confirm: All checks passed!
```

## Environment setup

1. Copy `.env.production.example` to `.env` (or `.env.example` for local tests).
2. Generate real random secrets:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Fill:
   - `JARVIS_SECRET_KEY`
   - `JARVIS_ADMIN_PASSWORD`
   - `JARVIS_API_TOKEN`
   - One LLM provider key.
4. Keep `SELF_IMPROVE_ENABLED=false`.
5. Do **not** set `BEA_SKIP_IMPROVEMENT_GATE`.
6. Set `CORS_ORIGINS` to your actual frontend origins.
7. Set `ENABLE_API_DOCS=0` if exposed to a non-local network.

## Inviting a tester

1. Add them to the private beta channel.
2. Send them:
   - This runbook (operator copy if needed).
   - [README_PUBLIC_BETA.md](../README_PUBLIC_BETA.md).
   - [docs/BETA_TESTER_GUIDE.md](BETA_TESTER_GUIDE.md).
   - [docs/PRIVACY_FOR_TESTERS.md](PRIVACY_FOR_TESTERS.md).
3. Ask them to confirm they have:
   - cloned the branch;
   - filled `.env` safely;
   - run the gate;
   - read the privacy rules.

## During the beta

### Daily

- Review new issues.
- Re-run `python scripts/private_beta_gate.py --json` after each code change.
- Ensure no `.env` files are committed.

### Weekly

- Triage issues/PRs and update `reports/private_beta/github_triage.md`.
- Reconcile `PUBLIC_BETA_CHECKLIST.md` with reality.
- Rotate any token that may have been shared by mistake.

### If a tester reports a security issue

1. Acknowledge privately within 24 hours.
2. Do not discuss details in public channels.
3. Reproduce in an isolated environment.
4. Fix on a branch, request a private review, then disclose a summary after the fix.

## Self-improvement (deliberate activation only)

Default state: **OFF**.

If a senior operator chooses to enable it:

1. Read `docs/SECURITY_AUDIT.md` §8.
2. Ensure `JARVIS_ALLOW_LOCAL_SANDBOX=1` is intentionally set if local sandbox is used.
3. Set `SELF_IMPROVE_ENABLED=true` or `BEA_CONTINUOUS_IMPROVEMENT=1`.
4. Keep `BEA_SKIP_IMPROVEMENT_GATE` unset.
5. Monitor logs and workspace/self_improvement/ closely.
6. Have a rollback plan.

## Rollback plan

If something goes wrong:

```bash
# Stop Béa
docker compose down
# Or kill the python process

# Restore env
cp .env.backup-<timestamp> .env

# Restart fresh
docker compose up -d --force-recreate
```

## External actions that remain human-only

- Rotate historically exposed secrets.
- Revoke hardcoded Flutter token if applicable.
- Force-push cleaned history if needed (already done; verify remote).
- Coordinate with testers and legal/compliance teams.

## Exit criteria for the private beta

Move to the next phase only when:

- `ready_for_private_beta` stays true for 2 weeks.
- No critical security issues are open.
- At least 5 testers have submitted useful feedback.
- Documentation has been updated with lessons learned.

Do **not** call it a public beta until `READY_FOR_PUBLIC_BETA: true` is explicitly set with a new checklist.
