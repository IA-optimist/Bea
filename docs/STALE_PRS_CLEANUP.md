# Béa — Stale PR Cleanup Report

> Report on open PRs that may be superseded by recent merges (#99–#111).
> This document does NOT close any PRs — it recommends actions for a human to
> execute manually after review.

---

## PR #93 — Windows Unicode safety + explicit --dry-run for alpha diagnostics

**Status:** Open
**Likely superseded by:** PR #104 (memory hygiene), PR #106 (seed profiles), PR #110 (ops runbook)
**Recommendation:** Review whether the Unicode/dry-run fixes are still needed. If the
files have been significantly modified since #93 was opened, close as superseded and
re-create a focused PR if any changes are still needed.

## PR #94 — Flutter v3 migration + APK rebuild

**Status:** Open
**Likely superseded by:** PR #105 (Flutter v3 APK migration confirmed + v1 deprecation plan)
**Recommendation:** Close as superseded. PR #105 already covers the Flutter v3 migration
documentation. If code changes from #94 are still needed, cherry-pick them into a new PR
on top of current main.

## PR #68 — Dependabot dependency alerts

**Status:** Open
**Recommendation:** Rebase onto current main. Many dependencies may have been updated
in recent merges. If the alerts are no longer relevant after rebasing, close. Otherwise,
create a dedicated dependency update PR.

## PR #27 — Docs audit (old)

**Status:** Open
**Recommendation:** Close as superseded. The docs have been significantly overhauled
in PRs #104, #106, #108, #110. Any remaining content from #27 should be re-evaluated
against the current docs structure.

## PR #26 — Docs audit (old)

**Status:** Open
**Recommendation:** Same as #27 — close as superseded. Re-evaluate any specific
content against current docs.

---

## General recommendation

1. Close #27 and #26 as superseded (docs have been rewritten).
2. Close #94 as superseded by #105.
3. Review #93 — if the Unicode fixes are still needed, rebase; otherwise close.
4. Rebase #68 (dependency alerts) or create a fresh dependency PR.
5. Do NOT merge any of these PRs without rebasing onto current main first — the
   codebase has changed significantly.
