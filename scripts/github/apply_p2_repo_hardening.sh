#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-IA-optimist/Bea}"
DEFAULT_BRANCH="${2:-main}"

echo "[1/4] Enforce safer GitHub Actions workflow permissions"
gh api -X PUT -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/actions/permissions/workflow" \
  -f default_workflow_permissions='read' \
  -F can_approve_pull_request_reviews=false >/dev/null

echo "[2/4] Enforce SHA pinning for Actions"
gh api -X PUT -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/actions/permissions" \
  -F enabled=true \
  -f allowed_actions='all' \
  -F sha_pinning_required=true >/dev/null

echo "[3/4] Configure branch protection on ${DEFAULT_BRANCH}"
gh api -X PUT -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/branches/${DEFAULT_BRANCH}/protection" \
  --input - <<'JSON' >/dev/null
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON

echo "[4/4] Create ruleset to protect workflow files"
gh api -X POST -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/rulesets" \
  --input - <<JSON >/dev/null
{
  "name": "Protect GitHub workflow files",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "pull_request"},
    {"type": "non_fast_forward"},
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": []
      }
    },
    {
      "type": "file_path_restriction",
      "parameters": {
        "restricted_file_paths": [
          ".github/workflows/**",
          ".github/actions/**"
        ]
      }
    }
  ],
  "bypass_actors": []
}
JSON

echo "Done. Running read-back checks..."

gh api "repos/${REPO}/actions/permissions/workflow"
gh api "repos/${REPO}/actions/permissions"
gh api "repos/${REPO}/branches/${DEFAULT_BRANCH}/protection" | head -c 500 && echo

echo "P2 hardening applied successfully."
