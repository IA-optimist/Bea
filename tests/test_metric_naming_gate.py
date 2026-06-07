"""Naming gate for Prometheus metrics.

Audit follow-up (observability): the repo currently has two metric
prefixes (`bea_*` and `business_*`); see
``docs/security/observability-audit.md`` for the full discussion.

This test enforces the GOING-FORWARD convention without breaking existing
metrics. Pre-existing `business_*` names live in an explicit allowlist so
the dashboards keep working; every NEW metric must satisfy the convention
or be added to the allowlist with a written justification in the PR.

Convention:

  - Counter: ``bea_<subsystem>_<thing>_total``
  - Histogram: ``bea_<subsystem>_<thing>_<unit>`` (`_seconds`,
    `_bytes`, `_ratio`)
  - Gauge: ``bea_<subsystem>_<thing>`` (suffix optional, but
    `_count`/`_ratio` recommended)
  - Summary: same as Histogram

To add a new metric in a NEW prefix (e.g. a brand-new service), bump
this test's allowlist with a justification.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SCAN_ROOTS = ("api", "core", "kernel", "agents", "business", "memory")

# Metric names known to predate the convention. Each entry MUST be
# justified by a comment line. Don't remove without a coordination PR
# that swaps the matching dashboards / alerts.
_GRANDFATHERED = {
    # business/business_engine.py — predates the bea_ prefix. Tracked
    # in docs/security/observability-audit.md item P1, recommendation:
    # dual-emit bea_business_* and retire these after dashboard swap.
    "business_opportunity_scans_total",
    "business_opportunities_found",
    "business_scan_duration_seconds",
    "business_product_builds_total",
    "business_deploy_duration_seconds",
    "business_compliance_checks_total",
    "business_pipeline_runs_total",
}

_COUNTER_RE = re.compile(r"^bea_[a-z][a-z0-9_]*_total$")
_HISTOGRAM_RE = re.compile(
    r"^bea_[a-z][a-z0-9_]*_(seconds|bytes|ratio)$"
)
_GAUGE_RE = re.compile(r"^bea_[a-z][a-z0-9_]*$")

_METRIC_CLASSES = {"Counter", "Histogram", "Gauge", "Summary"}

# Local helpers that wrap prometheus_client classes (audit-gated factories
# that handle ImportError + "Duplicated timeseries" gracefully). The first
# positional arg is still the metric name, so we treat them like the
# bare classes.
_METRIC_FACTORIES = {
    "_try_counter": "Counter",
    "_try_histogram": "Histogram",
    "_try_gauge": "Gauge",
    "_try_summary": "Summary",
}


def _walk_metric_calls(tree: ast.AST):
    """Yield (class_name, metric_name, ast_node) for each metric instantiation
    where the first positional argument is a string literal — both direct
    ``Counter("name", ...)`` and ``_try_counter("name", ...)`` factory calls."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = None
        if isinstance(func, ast.Name):
            called = func.id
        elif isinstance(func, ast.Attribute):
            called = func.attr

        cls = None
        if called in _METRIC_CLASSES:
            cls = called
        elif called in _METRIC_FACTORIES:
            cls = _METRIC_FACTORIES[called]
        if cls is None:
            continue

        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            yield cls, first.value, node


def _iter_python_files():
    for root_name in _SCAN_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "_legacy" in path.parts:
                continue
            yield path


def _collect_metrics() -> list[tuple[Path, str, str]]:
    out: list[tuple[Path, str, str]] = []
    for py in _iter_python_files():
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(text, filename=str(py))
        except SyntaxError:
            continue
        for cls, name, _node in _walk_metric_calls(tree):
            out.append((py.relative_to(_REPO_ROOT), cls, name))
    return out


def test_metric_definitions_discovered():
    """Sanity: we find at least the jwt_v2 + profiling + business set."""
    metrics = _collect_metrics()
    names = {m[2] for m in metrics}
    # Must find at least one from each of the three known subsystems.
    assert any(n.startswith("bea_jwt_v2_") for n in names), names
    assert "bea_profile_duration_seconds" in names, names
    assert "business_opportunity_scans_total" in names, names


def test_no_new_metric_violates_convention():
    """Every new metric must follow the convention or be allowlisted.
    Existing `business_*` are grandfathered ; future business_ metrics
    must use `bea_business_*` instead."""
    metrics = _collect_metrics()
    offenders: list[tuple[str, str, str]] = []
    for path, cls, name in metrics:
        if name in _GRANDFATHERED:
            continue
        if cls == "Counter":
            ok = bool(_COUNTER_RE.match(name))
        elif cls == "Histogram":
            ok = bool(_HISTOGRAM_RE.match(name))
        elif cls == "Gauge":
            ok = bool(_GAUGE_RE.match(name))
        elif cls == "Summary":
            ok = bool(_HISTOGRAM_RE.match(name))
        else:
            ok = True
        if not ok:
            offenders.append((str(path), cls, name))

    assert not offenders, (
        f"{len(offenders)} new metric(s) violate the naming convention "
        "(see docs/security/observability-audit.md):\n"
        + "\n".join(f"  {p} : {c}({n!r})" for p, c, n in offenders)
        + "\n\nFix the name (preferred) or add it to _GRANDFATHERED in "
        "this file with a written justification."
    )


def test_grandfathered_set_only_contains_real_metrics():
    """The allowlist must not drift — every entry must still exist in
    the codebase. If we removed a metric, drop it from _GRANDFATHERED
    so the gate stays honest."""
    metrics = {m[2] for m in _collect_metrics()}
    stale = sorted(_GRANDFATHERED - metrics)
    assert not stale, (
        f"_GRANDFATHERED contains {len(stale)} metric(s) that no longer "
        "exist in the codebase. Remove them so the allowlist stays tight:\n"
        + "\n".join(f"  {s}" for s in stale)
    )
