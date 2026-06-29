"""
agent_data/sql_policy.py — SQL safety policy for the Data Agent.

Rules:
  1. SELECT only — INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/TRUNCATE/EXEC rejected
  2. No stacked statements (multiple statements per query)
  3. No comment-based injection patterns
  4. LIMIT clause is injected if missing
  5. MAX_ROWS cap enforced
"""
from __future__ import annotations

import re
from dataclasses import dataclass


MAX_ROWS: int = 1000

# Forbidden SQL keywords that mutate state or execute arbitrary code
_FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|MERGE)\b", re.IGNORECASE),
    re.compile(r"\bINTO\b", re.IGNORECASE),      # INSERT INTO, SELECT INTO
    re.compile(r"--[^\n]*$", re.MULTILINE),        # inline SQL comments (injection risk)
    re.compile(r"/\*.*?\*/", re.DOTALL),            # block comments
    re.compile(r";\s*\S", re.IGNORECASE),           # stacked statements
]

_SELECT_REQUIRED = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_LIMIT_PATTERN   = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
_LIMIT_DIGIT     = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)


@dataclass
class SQLSafetyResult:
    safe: bool
    reason: str | None          # None when safe
    safe_query: str | None      # normalized query with LIMIT injected
    original_query: str

    @property
    def blocked(self) -> bool:
        return not self.safe


def check_sql_safety(query: str) -> SQLSafetyResult:
    """
    Run the full SQL safety check pipeline.

    Returns SQLSafetyResult.  If safe=True, safe_query contains the
    normalized query with LIMIT injected/enforced.
    """
    stripped = query.strip()

    # 1. Must start with SELECT
    if not _SELECT_REQUIRED.match(stripped):
        return SQLSafetyResult(
            safe=False,
            reason="only SELECT queries are allowed — this query does not start with SELECT",
            safe_query=None,
            original_query=query,
        )

    # 2. Check for forbidden patterns
    for pat in _FORBIDDEN_PATTERNS:
        m = pat.search(stripped)
        if m:
            return SQLSafetyResult(
                safe=False,
                reason=f"forbidden pattern detected: '{m.group()[:40]}' — only read-only SELECT is allowed",
                safe_query=None,
                original_query=query,
            )

    # 3. Inject or cap LIMIT
    if not _LIMIT_PATTERN.search(stripped):
        safe_q = stripped.rstrip(";") + f" LIMIT {MAX_ROWS}"
    else:
        # Cap existing LIMIT to MAX_ROWS
        def _cap_limit(m: re.Match[str]) -> str:
            existing = int(m.group(1))
            capped = min(existing, MAX_ROWS)
            return f"LIMIT {capped}"
        safe_q = _LIMIT_DIGIT.sub(_cap_limit, stripped)

    return SQLSafetyResult(
        safe=True,
        reason=None,
        safe_query=safe_q,
        original_query=query,
    )
