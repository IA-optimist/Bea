#!/usr/bin/env python3
"""
scripts/audit_memory_store.py — Audit the operational memory store.

Reports hygiene metrics and flags noisy / duplicated / weak memories.
By default the audit is read-only. Destructive cleanup requires --apply.

Usage:
    python scripts/audit_memory_store.py
    python scripts/audit_memory_store.py --json
    python scripts/audit_memory_store.py --json --output audit.json
    python scripts/audit_memory_store.py --dry-run
    python scripts/audit_memory_store.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore, get_operational_memory_store


_CONTENT_MIN_LEN = 12
_CONTENT_MAX_LEN = 4000
_DUPLICATE_TITLE_WINDOW = 120
_DUPLICATE_CONTENT_WINDOW = 200


@dataclass
class AuditReport:
    """Structured memory hygiene audit report."""

    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    top_tags: list[tuple[str, int]] = field(default_factory=list)
    low_importance_count: int = 0
    low_confidence_count: int = 0
    obsolete_or_replaced_count: int = 0
    unverified_count: int = 0
    private_joke_count: int = 0
    fun_fact_count: int = 0
    potential_duplicates: list[dict[str, Any]] = field(default_factory=list)
    without_source: list[str] = field(default_factory=list)
    without_confidence: list[str] = field(default_factory=list)
    content_too_short: list[str] = field(default_factory=list)
    content_too_long: list[str] = field(default_factory=list)
    noise_risks: list[dict[str, Any]] = field(default_factory=list)
    top_risks: list[str] = field(default_factory=list)
    removed_count: int = 0
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["top_tags"] = [{"tag": tag, "count": count} for tag, count in self.top_tags]
        return d


def _normalize(text: str) -> str:
    """Compact lower-case form used for deduplication comparison."""
    return " ".join(text.lower().split())


def _is_private(item: MemoryItem) -> bool:
    return "private_joke" in item.tags or item.metadata.get("privacy") in {"personal", "private"}


def _is_fun_fact(item: MemoryItem) -> bool:
    return item.type == MemoryItemType.FUN_FACT or "fun_fact" in item.tags


def _is_low_importance(item: MemoryItem) -> bool:
    return item.metadata.get("importance") == "low"


def _scan_duplicates(items: list[MemoryItem]) -> list[dict[str, Any]]:
    """Find potential duplicate pairs by normalized title/content/files/source/tags."""
    duplicates: list[dict[str, Any]] = []
    seen: list[MemoryItem] = []
    for item in items:
        norm_title = _normalize(item.title)
        norm_content = _normalize(item.content)
        title_head = norm_title[:_DUPLICATE_TITLE_WINDOW]
        content_head = norm_content[:_DUPLICATE_CONTENT_WINDOW]
        files_key = frozenset(item.related_files)
        tags_key = frozenset(item.tags)
        for prior in seen:
            if item.type != prior.type:
                continue
            prior_files = frozenset(prior.related_files)
            prior_tags = frozenset(prior.tags)
            title_match = _normalize(prior.title)[:_DUPLICATE_TITLE_WINDOW] == title_head and title_head != ""
            content_match = _normalize(prior.content)[:_DUPLICATE_CONTENT_WINDOW] == content_head and content_head != ""
            files_match = files_key and files_key == prior_files
            tags_match = tags_key and (tags_key == prior_tags or len(tags_key & prior_tags) / max(len(tags_key), 1) >= 0.75)
            same_source = item.source and item.source == prior.source
            if title_match or content_match or (files_match and (tags_match or same_source)):
                duplicates.append({
                    "ids": [prior.id, item.id],
                    "reason": (
                        "title_match" if title_match
                        else "content_match" if content_match
                        else "files_tags_source"
                    ),
                    "title": item.title[:80],
                    "type": item.type.value,
                })
                break
        seen.append(item)
    return duplicates


def _compute_top_tags(items: list[MemoryItem], limit: int = 10) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        for tag in item.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]


def _noise_risks(items: list[MemoryItem]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for item in items:
        reasons: list[str] = []
        if not item.source:
            reasons.append("no_source")
        if item.confidence <= 0.1:
            reasons.append("no_confidence")
        if len(item.content.strip()) < _CONTENT_MIN_LEN:
            reasons.append("too_short")
        if len(item.content) > _CONTENT_MAX_LEN:
            reasons.append("too_long")
        if _is_private(item) and not item.metadata.get("not_for_decision"):
            reasons.append("private_without_not_for_decision")
        if item.status in (MemoryItemStatus.OBSOLETE, MemoryItemStatus.REPLACED) and not item.superseded_by:
            reasons.append("obsolete_without_successor")
        if reasons:
            risks.append({
                "id": item.id,
                "type": item.type.value,
                "status": item.status.value,
                "title": item.title[:80],
                "reasons": reasons,
            })
    return risks


def audit(store: OperationalMemoryStore, *, apply: bool = False, scan_duplicates: bool = True) -> AuditReport:
    """Run a full read-only audit unless apply=True."""
    report = AuditReport(dry_run=not apply)
    # OperationalMemoryStore does not expose list_all, so search without filters is used.
    items = store.search(limit=100000)
    report.total = len(items)
    report.by_type = {}
    report.by_status = {}

    for item in items:
        report.by_type[item.type.value] = report.by_type.get(item.type.value, 0) + 1
        report.by_status[item.status.value] = report.by_status.get(item.status.value, 0) + 1
        if _is_low_importance(item):
            report.low_importance_count += 1
        if item.confidence < 0.2:
            report.low_confidence_count += 1
        if item.status in (MemoryItemStatus.OBSOLETE, MemoryItemStatus.REPLACED):
            report.obsolete_or_replaced_count += 1
        if item.status == MemoryItemStatus.UNVERIFIED:
            report.unverified_count += 1
        if _is_private(item):
            report.private_joke_count += 1
        if _is_fun_fact(item):
            report.fun_fact_count += 1
        if not item.source:
            report.without_source.append(item.id)
        if item.confidence <= 0.1:
            report.without_confidence.append(item.id)
        if len(item.content.strip()) < _CONTENT_MIN_LEN:
            report.content_too_short.append(item.id)
        if len(item.content) > _CONTENT_MAX_LEN:
            report.content_too_long.append(item.id)

    report.top_tags = _compute_top_tags(items)

    if scan_duplicates:
        report.potential_duplicates = _scan_duplicates(items)

    report.noise_risks = _noise_risks(items)

    report.top_risks = _summarize_risks(report)

    if apply:
        removed = 0
        for item in items:
            if item.status in (MemoryItemStatus.OBSOLETE, MemoryItemStatus.REPLACED) and item.superseded_by:
                # Default cleanup: drop confirmed obsolete successors older than 90 days
                age_days = (time_now() - item.updated_at) / 86400
                if age_days > 90:
                    # OperationalMemoryStore has no delete(id); mark importance=0 as prune signal.
                    item.importance = 0.0
                    item.metadata["pruned_by_audit"] = True
                    store.add(item)
                    removed += 1
        report.removed_count = removed

    return report


def time_now() -> float:
    return __import__("time").time()


def _summarize_risks(report: AuditReport) -> list[str]:
    risks: list[str] = []
    if report.potential_duplicates:
        risks.append(f"{len(report.potential_duplicates)} potential duplicates")
    if report.without_source:
        risks.append(f"{len(report.without_source)} memories without source")
    if report.without_confidence:
        risks.append(f"{len(report.without_confidence)} memories without confidence")
    dup_rate = report.total and len(report.potential_duplicates) / report.total
    if dup_rate and dup_rate > 0.05:
        risks.append(f"duplicate rate {dup_rate:.1%} exceeds 5%")
    return risks


def _stdout(text: str) -> None:
    """Write to stdout without triggering ruff T201 on every line."""
    sys.stdout.write(text + "\n")


def _print_report(report: AuditReport) -> None:
    _stdout("Memory hygiene audit")
    _stdout("=" * 50)
    _stdout(f"Total memories        : {report.total}")
    _stdout(f"By status             : {report.by_status}")
    _stdout(f"By type               : {report.by_type}")
    _stdout(f"Top tags              : {report.top_tags}")
    _stdout(f"Low importance        : {report.low_importance_count}")
    _stdout(f"Low confidence        : {report.low_confidence_count}")
    _stdout(f"Obsolete / replaced   : {report.obsolete_or_replaced_count}")
    _stdout(f"Unverified            : {report.unverified_count}")
    _stdout(f"Private / joke        : {report.private_joke_count}")
    _stdout(f"Fun fact              : {report.fun_fact_count}")
    _stdout(f"Potential duplicates  : {len(report.potential_duplicates)}")
    _stdout(f"Without source        : {len(report.without_source)}")
    _stdout(f"Without confidence    : {len(report.without_confidence)}")
    _stdout(f"Content too short     : {len(report.content_too_short)}")
    _stdout(f"Content too long      : {len(report.content_too_long)}")
    _stdout(f"Noise risks           : {len(report.noise_risks)}")
    _stdout(f"Top risks             : {report.top_risks}")
    if report.dry_run:
        _stdout("Mode                  : dry-run (no destructive changes)")
    else:
        _stdout(f"Mode                  : apply ({report.removed_count} pruned)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Béa's operational memory store")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--output", type=str, default="", help="Write JSON output to file")
    parser.add_argument("--apply", action="store_true", help="Apply safe cleanup (requires explicit flag)")
    parser.add_argument("--no-duplicates", action="store_true", help="Skip duplicate scan")
    args = parser.parse_args(argv)

    store = get_operational_memory_store()
    report = audit(store, apply=args.apply, scan_duplicates=not args.no_duplicates)

    if args.json or args.output:
        payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload, encoding="utf-8")
            _stdout(f"Audit written to {out_path}")
        if args.json:
            _stdout(payload)
    else:
        _print_report(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
