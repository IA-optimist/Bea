#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# verify_prod.sh — Zero-impact production diagnostic
# ──────────────────────────────────────────────────────────────────
# Usage : sur VPS1 ou n'importe où avec accès réseau au domaine.
#   bash scripts/verify_prod.sh [--verbose]
#
# Checks (aucun effet de bord, 100% read-only) :
#   A. Local VPS state  (si lancé depuis VPS1 — container, logs, .env)
#   B. HTTP endpoints   (health, /auth/me path, versions)
#   C. Cookie auth flow (login + /auth/me via cookie, logout)
#   D. GitHub Actions   (last workflow runs — requires gh CLI + auth)
#   E. Git state        (local vs origin/main, uncommitted)
#
# Codes de sortie :
#   0 = tout OK
#   1 = warnings mineurs (section C ou D peuvent être skipped en safe)
#   2 = erreur critique (health down, container dead)
# ──────────────────────────────────────────────────────────────────
set -uo pipefail

DOMAIN="${DOMAIN:-jarvis.jarvismaxapp.co.uk}"
CONTAINER="${CONTAINER:-jarvis_core}"
REPO_DIR="${REPO_DIR:-/root/Jarvismax-master}"
LOCAL_HEALTH="http://localhost:8000/api/v2/health"
PUBLIC_HEALTH="https://${DOMAIN}/api/v2/health"
VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

FAIL=0
WARN=0
ok()    { printf '  \033[0;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[0;33m⚠\033[0m %s\n' "$*"; WARN=$((WARN+1)); }
fail()  { printf '  \033[0;31m✗\033[0m %s\n' "$*" >&2; FAIL=$((FAIL+1)); }
info()  { printf '  \033[0;34m→\033[0m %s\n' "$*"; }
section(){ printf '\n\033[1;36m%s\033[0m\n' "$*"; }

# ── A. Local VPS state ─────────────────────────────────────
section "[A] Local VPS state"

ON_VPS=0
if [[ -f "$REPO_DIR/.env" ]] && command -v docker >/dev/null; then
  ON_VPS=1
fi

if [[ $ON_VPS -eq 1 ]]; then
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    UPTIME=$(docker inspect --format '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null || echo "?")
    STATUS=$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo "?")
    ok "container ${CONTAINER} running (started: $UPTIME, health: $STATUS)"
  else
    fail "container ${CONTAINER} NOT running"
    if [[ $VERBOSE -eq 1 ]]; then
      info "last 5 container events:"
      docker ps -a --filter "name=${CONTAINER}" --format '{{.Status}}  {{.Names}}' | head -5
    fi
  fi

  if [[ -f "$REPO_DIR/.env" ]]; then
    # Check .env has no CHANGE_ME (rotated)
    if grep -q "CHANGE_ME" "$REPO_DIR/.env" 2>/dev/null; then
      warn ".env contains CHANGE_ME placeholders — rotation incomplete"
      [[ $VERBOSE -eq 1 ]] && grep -n "CHANGE_ME" "$REPO_DIR/.env" | head -3 | while read -r l; do info "$l"; done
    else
      ok ".env has no CHANGE_ME placeholders"
    fi
    # Check perms
    PERM=$(stat -c %a "$REPO_DIR/.env" 2>/dev/null || echo "?")
    if [[ "$PERM" == "600" || "$PERM" == "400" ]]; then
      ok ".env perms secure ($PERM)"
    else
      warn ".env perms $PERM (should be 600 or 400)"
    fi
  fi

  # Recent errors in logs
  if [[ $VERBOSE -eq 1 ]]; then
    ERR_COUNT=$(docker logs --since 1h "$CONTAINER" 2>&1 | grep -ciE "error|fatal|traceback" | head -1 || echo 0)
    info "errors in last 1h: $ERR_COUNT"
  fi
else
  info "not running from VPS (skipped local checks)"
fi

# ── B. HTTP endpoints ─────────────────────────────────────
section "[B] HTTP endpoints"

probe_http() {
  local url="$1"
  local label="$2"
  local code
  code=$(curl -sI --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo "000")
  if [[ "$code" == "200" ]]; then
    ok "$label → 200 OK ($url)"
  elif [[ "$code" == "401" || "$code" == "403" ]]; then
    ok "$label → $code (expected for auth-gated endpoint)"
  elif [[ "$code" == "000" ]]; then
    fail "$label → NO RESPONSE ($url) — host unreachable"
  else
    warn "$label → HTTP $code"
  fi
}

probe_http "$PUBLIC_HEALTH"                         "public health"
probe_http "https://${DOMAIN}/api/v3/system/readiness"  "public readiness"
probe_http "https://${DOMAIN}/docs"                 "public docs"
probe_http "https://${DOMAIN}/auth/login"           "public /auth/login"

[[ $ON_VPS -eq 1 ]] && probe_http "$LOCAL_HEALTH" "local container health"

# ── C. Cookie auth flow ───────────────────────────────────
section "[C] Cookie auth flow"

if [[ -z "${JARVIS_TEST_USER:-}" || -z "${JARVIS_TEST_PASSWORD:-}" ]]; then
  info "skipped (set JARVIS_TEST_USER + JARVIS_TEST_PASSWORD to run)"
else
  COOKIE_JAR=$(mktemp)
  trap 'rm -f "$COOKIE_JAR"' EXIT

  LOGIN_CODE=$(curl -s -c "$COOKIE_JAR" -o /dev/null -w '%{http_code}' --max-time 5 \
    -X POST "https://${DOMAIN}/api/v2/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$JARVIS_TEST_USER\",\"password\":\"$JARVIS_TEST_PASSWORD\"}" \
    2>/dev/null || echo "000")

  if [[ "$LOGIN_CODE" == "200" ]]; then
    ok "login → 200"
    if grep -q "jarvis_token" "$COOKIE_JAR" 2>/dev/null; then
      ok "Set-Cookie jarvis_token received"
      # Check HttpOnly flag
      if grep "jarvis_token" "$COOKIE_JAR" 2>/dev/null | awk '{print $7}' | grep -qE "TRUE|true"; then
        ok "HttpOnly flag set"
      else
        warn "HttpOnly flag not set (XSS risk)"
      fi
    else
      fail "no jarvis_token cookie in response"
    fi

    ME_CODE=$(curl -s -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' --max-time 5 \
      "https://${DOMAIN}/auth/me" 2>/dev/null || echo "000")
    if [[ "$ME_CODE" == "200" ]]; then
      ok "/auth/me with cookie → 200"
    else
      fail "/auth/me with cookie → $ME_CODE"
    fi

    LOGOUT_CODE=$(curl -s -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' --max-time 5 \
      -X POST "https://${DOMAIN}/api/v2/auth/logout" 2>/dev/null || echo "000")
    [[ "$LOGOUT_CODE" == "200" ]] && ok "logout → 200" || warn "logout → $LOGOUT_CODE"
  else
    fail "login failed → HTTP $LOGIN_CODE"
  fi
fi

# ── D. GitHub Actions ─────────────────────────────────────
section "[D] GitHub Actions (last 5 runs)"

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    if [[ $VERBOSE -eq 1 ]]; then
      gh run list --limit 5 --repo UniTy01/Jarvismax-master 2>&1 | sed 's/^/    /'
    else
      FAILED_RUNS=$(gh run list --limit 5 --repo UniTy01/Jarvismax-master --json conclusion --jq '[.[] | select(.conclusion == "failure")] | length' 2>/dev/null || echo "?")
      if [[ "$FAILED_RUNS" == "0" ]]; then
        ok "last 5 runs : all green"
      elif [[ "$FAILED_RUNS" == "?" ]]; then
        warn "could not query gh api"
      else
        warn "$FAILED_RUNS failed runs in last 5"
      fi
    fi
  else
    info "skipped (gh not authenticated — run 'gh auth login')"
  fi
else
  info "skipped (gh CLI not installed)"
fi

# ── E. Git state ──────────────────────────────────────────
section "[E] Git repo state"

if [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "?")
  REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "?")
  if [[ "$LOCAL" == "$REMOTE" ]]; then
    ok "HEAD == origin/main ($(echo "$LOCAL" | cut -c1-7))"
  else
    warn "HEAD != origin/main (local: $(echo "$LOCAL" | cut -c1-7), remote: $(echo "$REMOTE" | cut -c1-7))"
    info "→ local is $(git rev-list --count "$REMOTE..$LOCAL" 2>/dev/null || echo '?') ahead, $(git rev-list --count "$LOCAL..$REMOTE" 2>/dev/null || echo '?') behind"
  fi

  if git diff --quiet && git diff --cached --quiet; then
    ok "working tree clean"
  else
    warn "uncommitted changes present"
    [[ $VERBOSE -eq 1 ]] && git status --short | head -5 | while read -r l; do info "$l"; done
  fi
else
  info "skipped (not in a git repo)"
fi

# ── Summary ───────────────────────────────────────────────
section "Summary"
if [[ $FAIL -eq 0 && $WARN -eq 0 ]]; then
  printf '\033[1;32m  ALL CHECKS PASSED\033[0m\n'
  exit 0
elif [[ $FAIL -eq 0 ]]; then
  printf '\033[1;33m  %d WARNINGS, 0 FAILURES\033[0m\n' "$WARN"
  exit 1
else
  printf '\033[1;31m  %d FAILURES, %d WARNINGS\033[0m\n' "$FAIL" "$WARN"
  exit 2
fi
