"""Soft enforcement of the log event-name convention.

Audit observability quick-win #5: every `log.<level>(...)` call's first
positional argument must follow the regex
``^[a-z][a-z0-9_]*(?:\\.[a-z][a-z0-9_]*)*$``. See
``docs/observability/log-events.md`` for the rationale.

The test walks the AST so we only inspect actual `log.*` calls, not
strings that happen to look like event names.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = ("api", "core", "kernel", "agents")

_EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_LEVELS = {"info", "warning", "error", "debug"}

# Event names that predate the convention (audit 2026-05-29). Locked
# from `quality/legacy_log_event_names.json` so new violations fail
# while the existing ones can be cleaned up incrementally.
import json as _json
_BASELINE_PATH = _REPO_ROOT / "quality" / "legacy_log_event_names.json"
try:
    _GRANDFATHERED: set[str] = set(_json.loads(
        _BASELINE_PATH.read_text(encoding="utf-8")
    ))
except (OSError, _json.JSONDecodeError):
    _GRANDFATHERED = set()


def _iter_python_files():
    for root_name in _SCAN_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "_legacy" in path.parts:
                continue
            yield path


def _walk_log_calls(tree: ast.AST):
    """Yield (event_name, ast_node) for each `log.<level>("event", ...)`
    call where the first positional arg is a string literal.

    Catches both ``log.info`` and ``mylogger.info`` if the caller uses
    a non-``log`` variable name — we match the attribute regardless of
    the receiver name to keep the check broad.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _LEVELS:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            yield first.value, node


def _parse_safely(py: Path) -> ast.AST | None:
    try:
        text = py.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    # Strip BOM if present — some files in the codebase still carry
    # U+FEFF which ast.parse rejects.
    if text.startswith("﻿"):
        text = text.lstrip("﻿")
    try:
        return ast.parse(text, filename=str(py))
    except SyntaxError:
        return None


def _collect_violations() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for py in _iter_python_files():
        tree = _parse_safely(py)
        if tree is None:
            continue
        for name, node in _walk_log_calls(tree):
            if name in _GRANDFATHERED:
                continue
            # Skip f-strings — they show up as Constant("") with the
            # template stripped, but we only see real Constant values here.
            if not name:
                continue
            # Skip event names that contain explicit format placeholders.
            # We can't validate them statically.
            if "{" in name or "%" in name:
                continue
            if not _EVENT_NAME_RE.match(name):
                rel = py.relative_to(_REPO_ROOT).as_posix()
                out.append((rel, node.lineno, name))
    return out


def test_event_names_follow_convention():
    violations = _collect_violations()
    assert not violations, (
        f"{len(violations)} log call(s) emit an event name that violates "
        "the convention (see docs/observability/log-events.md):\n"
        + "\n".join(f"  {p}:{ln}  {name!r}" for p, ln, name in violations)
        + "\n\nFix the event name or add it to _GRANDFATHERED in this "
        "test with a written justification."
    )


def test_baseline_does_not_track_disappeared_events():
    """If a baselined event has been removed from the codebase, drop
    it from the JSON so the ratchet locks the new clean state in."""
    all_events: set[str] = set()
    for py in _iter_python_files():
        tree = _parse_safely(py)
        if tree is None:
            continue
        for name, _node in _walk_log_calls(tree):
            if name:
                all_events.add(name)
    stale = sorted(_GRANDFATHERED - all_events)
    assert not stale, (
        f"{len(stale)} grandfathered event name(s) no longer appear in "
        "the codebase. Remove them from quality/legacy_log_event_names.json "
        "so the ratchet stays tight:\n"
        + "\n".join(f"  {s!r}" for s in stale[:20])
        + ("" if len(stale) <= 20 else f"\n  ... and {len(stale) - 20} more")
    )


def test_at_least_one_event_was_scanned():
    """Sanity — if the AST walker breaks, this test catches a 0-call run."""
    sample = 0
    for p in _iter_python_files():
        tree = _parse_safely(p)
        if tree is None:
            continue
        sample += sum(1 for _ in _walk_log_calls(tree))
    assert sample > 100, (
        f"the AST walker only found {sample} log calls — something is off "
        "with the scan; expected hundreds."
    )
