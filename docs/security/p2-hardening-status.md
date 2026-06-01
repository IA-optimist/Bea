# P2 GitHub hardening status (IA-optimist/Bea)

Date: 2026-06-01

## ✅ Applied automatically
- GitHub Actions workflow permissions:
  - `default_workflow_permissions = read`
  - `can_approve_pull_request_reviews = false`
- GitHub Actions policy:
  - `enabled = true`
  - `allowed_actions = all`
  - `sha_pinning_required = true`

## ❌ Blocked by GitHub plan gate (private repository)
- Branch protection on `main`
- Repository rulesets (including protection for `.github/workflows/**` and `.github/actions/**`)

GitHub API response (both endpoints):
> `403 Upgrade to GitHub Pro or make this repository public to enable this feature.`

## Option B selected
Option B = upgrade plan to enable private-repo protections.

Because billing/subscription is account-sensitive, this step cannot be executed through CLI/API without access to the account billing flow.

Direct upgrade link:
- https://github.com/settings/billing

## One-command completion after upgrade
After plan upgrade is active, run:

```bash
bash scripts/github/apply_p2_repo_hardening.sh IA-optimist/Bea main
```

This script is idempotent for permissions and performs read-back checks at the end.
