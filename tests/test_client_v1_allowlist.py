"""tests/test_client_v1_allowlist.py — Guard against new /api/v1 calls in client surfaces.

Scans all client surfaces for calls to /api/v1/* endpoints and enforces an
explicit allowlist. Any v1 call NOT on the allowlist fails CI immediately,
preventing silent v1 tech debt accumulation.

Allowlisted v1 calls are temporary — each has a TODO(v3-migration) comment
in the source and a corresponding entry in docs/FRONTEND_SURFACES.md.

To add a new exception (ONLY when strictly necessary):
  1. Add it to _V1_ALLOWLIST with a justification string.
  2. Add the corresponding TODO(v3-migration) comment in the source.
  3. Update docs/FRONTEND_SURFACES.md.
  4. Do NOT add new v1 calls — extend v3 instead.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent

# ── Client surface directories to scan ────────────────────────────────────────
_CLIENT_DIRS = [
    _ROOT / "beamax_app",
    _ROOT / "frontend",
    _ROOT / "static",
    _ROOT / "orchestrate-cli",
]

# ── File extensions to check in each surface ──────────────────────────────────
_EXTENSIONS = {".dart", ".ts", ".tsx", ".js", ".html", ".py"}

# ── Authorised v1 calls — (file_suffix, url_fragment) ─────────────────────────
# file_suffix: path relative to _ROOT, used as substring match
# url_fragment: the /api/v1/... substring expected in that file
#
# EVERY entry here must have a TODO(v3-migration) comment in the source and
# a documented migration target in docs/FRONTEND_SURFACES.md.
#
# Flutter migration complete (PR #90 + PR #91, 2026-06-21): all 3 Flutter v1
# calls (pause/resume/stream) migrated to v3. Allowlist is now empty — any
# new v1 call in a client surface will fail CI immediately.
_V1_ALLOWLIST: list[tuple[str, str]] = []


def _collect_v1_hits() -> list[tuple[str, int, str]]:
    """Return (rel_path, lineno, line) for every /api/v1 call found in clients."""
    hits: list[tuple[str, int, str]] = []

    for surface_dir in _CLIENT_DIRS:
        if not surface_dir.exists():
            continue
        for fpath in surface_dir.rglob("*"):
            if fpath.suffix not in _EXTENSIONS:
                continue
            if any(skip in str(fpath) for skip in ("__pycache__", "node_modules", ".dart_tool", "build/")):
                continue
            try:
                for lineno, line in enumerate(fpath.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if re.search(r"['\"`/]/api/v1/", line):
                        rel = str(fpath.relative_to(_ROOT)).replace("\\", "/")
                        hits.append((rel, lineno, line.strip()))
            except (OSError, UnicodeDecodeError):
                continue
    return hits


def _is_allowlisted(rel_path: str, line: str) -> bool:
    """Return True if this (file, line) matches a known allowlist entry."""
    for file_suffix, url_fragment in _V1_ALLOWLIST:
        if file_suffix.replace("\\", "/") in rel_path and url_fragment in line:
            return True
    return False


class TestClientV1Allowlist:
    def test_v1_allowlist_is_empty_after_flutter_v3_migration(self):
        """Flutter v3 migration is complete; no client v1 exceptions remain."""
        assert _V1_ALLOWLIST == [], (
            "Client /api/v1 allowlist must stay empty after Flutter v3 migration. "
            "A v1 return requires an explicit allowlist entry plus documented justification."
        )

    def test_flutter_api_service_has_no_v1_runtime_calls(self):
        """api_service.dart must not reintroduce runtime /api/v1 calls."""
        api_service = _ROOT / "beamax_app" / "lib" / "services" / "api_service.dart"
        content = api_service.read_text(encoding="utf-8")
        violations = []
        for lineno, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("///"):
                continue
            if re.search(r"['\"`/]/api/v1/", stripped):
                violations.append(f"beamax_app/lib/services/api_service.dart:{lineno}  {stripped}")

        assert not violations, (
            "Flutter api_service.dart reintroduced /api/v1 runtime call(s). "
            "Use /api/v3, or add an explicit allowlist entry with justification:\n"
            + "\n".join(violations)
        )

    def test_no_new_v1_calls_in_client_surfaces(self):
        """Fail if any client surface calls /api/v1/* outside the allowlist.

        To add a legitimate exception, update _V1_ALLOWLIST in this file
        AND docs/FRONTEND_SURFACES.md.
        """
        hits = _collect_v1_hits()
        violations = [
            (path, lineno, line)
            for path, lineno, line in hits
            if not _is_allowlisted(path, line)
        ]
        if violations:
            msg = (
                "Unauthorized /api/v1 call(s) found in client surfaces.\n"
                "Use /api/v3 for new endpoints. If truly necessary, add to\n"
                "_V1_ALLOWLIST in tests/test_client_v1_allowlist.py with a\n"
                "justification and update docs/FRONTEND_SURFACES.md.\n\n"
            )
            for path, lineno, line in violations:
                msg += f"  {path}:{lineno}  {line}\n"
            raise AssertionError(msg)

    def test_allowlisted_calls_still_exist(self):
        """Warn if an allowlisted v1 call has been removed (migration done).

        If an allowlist entry no longer matches any file, the migration may be
        complete — remove the entry from _V1_ALLOWLIST and docs/FRONTEND_SURFACES.md.
        """
        hits = _collect_v1_hits()
        all_hits_text = [(path, line) for path, _, line in hits]

        stale: list[tuple[str, str]] = []
        for file_suffix, url_fragment in _V1_ALLOWLIST:
            found = any(
                file_suffix.replace("\\", "/") in path and url_fragment in line
                for path, line in all_hits_text
            )
            if not found:
                stale.append((file_suffix, url_fragment))

        if stale:
            msg = (
                "Allowlisted v1 call(s) no longer found — migration may be complete!\n"
                "Remove these entries from _V1_ALLOWLIST in this file\n"
                "and update docs/FRONTEND_SURFACES.md:\n\n"
            )
            for file_suffix, url_fragment in stale:
                msg += f"  {file_suffix!r}  {url_fragment!r}\n"
            raise AssertionError(msg)

    def test_frontend_surfaces_doc_exists(self):
        """docs/FRONTEND_SURFACES.md must exist (required for v1 allowlist governance)."""
        doc = _ROOT / "docs" / "FRONTEND_SURFACES.md"
        assert doc.exists(), (
            "docs/FRONTEND_SURFACES.md is missing. "
            "This document must exist to govern the v1 allowlist."
        )
        content = doc.read_text(encoding="utf-8")
        assert "allowlist" in content.lower() or "allowlisted" in content.lower() or "v1 calls" in content.lower(), (
            "docs/FRONTEND_SURFACES.md does not mention v1 allowlist or v1 calls"
        )

    def test_static_html_has_no_v1_calls(self):
        """static/app.html and cockpit.html must remain v1-free (canonical surfaces)."""
        for fname in ("app.html", "cockpit.html"):
            fpath = _ROOT / "static" / fname
            if not fpath.exists():
                continue
            content = fpath.read_text(encoding="utf-8")
            v1_calls = re.findall(r"['\"`/]/api/v1/[^'\"`\s]+", content)
            assert not v1_calls, (
                f"static/{fname} has v1 call(s): {v1_calls}. "
                "Canonical surfaces must use v2/v3 only."
            )

    def test_frontend_react_has_no_v1_calls(self):
        """frontend/ React app must have no v1 calls."""
        frontend = _ROOT / "frontend" / "src"
        if not frontend.exists():
            return
        violations = []
        for fpath in frontend.rglob("*"):
            if fpath.suffix not in {".ts", ".tsx", ".js"}:
                continue
            try:
                for lineno, line in enumerate(fpath.read_text(encoding="utf-8").splitlines(), 1):
                    if re.search(r"['\"`/]/api/v1/", line):
                        rel = str(fpath.relative_to(_ROOT)).replace("\\", "/")
                        violations.append(f"{rel}:{lineno}  {line.strip()}")
            except (OSError, UnicodeDecodeError):
                continue
        assert not violations, (
            "frontend/ React app has v1 call(s) — use v2/v3:\n" + "\n".join(violations)
        )
