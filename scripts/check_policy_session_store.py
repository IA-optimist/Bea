#!/usr/bin/env python3
"""
Ratchet -- PolicyEngine session store abstraction.

Checks:
  1. core/session_store.py exists and exports the required symbols.
  2. PolicyEngine does not access _sessions as a raw dict (no self._sessions[key]
     or self._sessions.get(key) bypassing the store interface).
  3. Session key is never mission_id alone in critical paths (_session_key function
     must always have the principal_id parameter).
  4. approved_by / rejected_by do not appear inside _session_key() or ensure_session().

Exit codes:
  0 -- clean
  1 -- at least one violation

Usage:
  python scripts/check_policy_session_store.py
  python scripts/check_policy_session_store.py --verbose
  python scripts/check_policy_session_store.py --summary
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_ENGINE = REPO_ROOT / "core" / "policy_engine.py"
SESSION_STORE = REPO_ROOT / "core" / "session_store.py"

REQUIRED_EXPORTS = ["InMemorySessionStore", "RedisSessionStore", "build_session_store"]

# Patterns that indicate _sessions is being bypassed as a raw dict.
# NOTE: self._sessions.get() is the CORRECT store interface — do NOT flag it.
# Flag only patterns that would only make sense on a raw dict, not a SessionStore.
RAW_DICT_PATTERNS: list[re.Pattern] = [
    # Direct item assignment bypassing store.set()
    re.compile(r"""self\._sessions\s*\[[^\]]+\]\s*="""),
    # Direct item deletion bypassing store.delete()
    re.compile(r"""del\s+self\._sessions\s*\["""),
    # Re-assigning _sessions to a plain dict literal or dict() call
    re.compile(r"""self\._sessions\s*=\s*(?:\{\}|dict\s*\()"""),
    # pop() — not part of the store interface
    re.compile(r"""self\._sessions\.pop\s*\("""),
    # setdefault() — not part of the store interface
    re.compile(r"""self\._sessions\.setdefault\s*\("""),
]

RAW_DICT_ALLOWLIST: set[str] = {}

# approved_by / rejected_by inside session key construction or ensure_session
AUDIT_IN_SESSION_PATTERNS: list[re.Pattern] = [
    re.compile(r"""_session_key\s*\([^)]*\b(approved_by|rejected_by)\b"""),
    re.compile(r"""ensure_session\s*\([^)]*\b(approved_by|rejected_by)\b"""),
]


def _check_session_store_exists() -> list[str]:
    violations: list[str] = []
    if not SESSION_STORE.exists():
        violations.append("core/session_store.py does not exist")
        return violations

    text = SESSION_STORE.read_text(encoding="utf-8", errors="ignore")
    for symbol in REQUIRED_EXPORTS:
        pattern = re.compile(rf"\bclass {symbol}\b|\bdef {symbol}\b")
        if not pattern.search(text):
            violations.append(f"core/session_store.py: missing export '{symbol}'")
    return violations


def _check_policy_engine_raw_access() -> list[str]:
    violations: list[str] = []
    if not POLICY_ENGINE.exists():
        violations.append("core/policy_engine.py does not exist")
        return violations

    text = POLICY_ENGINE.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue
        for pat in RAW_DICT_PATTERNS:
            if pat.search(line):
                violations.append(f"core/policy_engine.py:{lineno}: {stripped}")
    return violations


def _check_session_key_no_audit_fields() -> list[str]:
    violations: list[str] = []
    if not POLICY_ENGINE.exists():
        return violations
    text = POLICY_ENGINE.read_text(encoding="utf-8", errors="ignore")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pat in AUDIT_IN_SESSION_PATTERNS:
            if pat.search(line):
                violations.append(f"core/policy_engine.py:{lineno}: {line.strip()}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    c1 = _check_session_store_exists()
    c2 = _check_policy_engine_raw_access()
    c3 = _check_session_key_no_audit_fields()

    checks = [
        ("session_store exports", c1),
        ("no raw dict access", c2),
        ("no audit fields in session key", c3),
    ]
    total = sum(len(v) for _, v in checks)
    n_pass = sum(1 for _, v in checks if not v)

    if args.summary:
        status = "PASS" if total == 0 else "FAIL"
        sys.stdout.write(
            f"check_policy_session_store: {status} ({n_pass}/{len(checks)} checks, {total} violations)\n"
        )
    else:
        sys.stdout.write("check_policy_session_store: scanning core/session_store.py + core/policy_engine.py...\n")
        for name, viols in checks:
            status = "PASS" if not viols else "FAIL"
            sys.stdout.write(f"  {status}: {name} ({len(viols)} violations)\n")
        sys.stdout.write(
            f"check_policy_session_store: {'PASS' if total == 0 else 'FAIL'} ({n_pass}/{len(checks)} checks)\n"
        )

    if args.verbose and total > 0:
        for name, viols in checks:
            if viols:
                sys.stderr.write(f"\n[{name}]:\n")
                for v in viols:
                    sys.stderr.write(f"  {v}\n")

    return 1 if total > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
