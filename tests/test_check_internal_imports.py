"""tests/test_check_internal_imports.py — test suite for the import audit ratchet.

Four tests:
  1. test_broken_unprotected_exits_1      — naked broken import → exit 1
  2. test_broken_protected_exits_0        — protected broken import → exit 0
  3. test_test_files_are_ignored          — broken import in test file → exit 0, in ignored_tests
  4. test_kernel_boundary_not_weakened    — ratchet: run against real repo, assert no new breakage
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_internal_imports.py"


def _run(tmp_path: Path, extra_args: list[str] | None = None) -> tuple[int, dict]:
    """Run the script against *tmp_path* and return (exit_code, parsed_json)."""
    args = [sys.executable, str(SCRIPT), "--root", str(tmp_path)]
    if extra_args:
        args.extend(extra_args)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    stdout = result.stdout.strip()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = {}
    return result.returncode, data


def _make_internal_dir(tmp_path: Path, name: str = "core") -> None:
    """Create a minimal internal namespace package so other files can be in the tree."""
    pkg = tmp_path / name
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: naked broken import → exit 1
# ---------------------------------------------------------------------------

def test_broken_unprotected_exits_1(tmp_path: Path) -> None:
    """A naked import of a non-existent internal module must cause exit 1."""
    _make_internal_dir(tmp_path, "core")

    broken = tmp_path / "mymodule.py"
    broken.write_text(
        textwrap.dedent("""\
            from core.nonexistent_module_xyz import SomeClass
        """),
        encoding="utf-8",
    )

    exit_code, data = _run(tmp_path)

    assert exit_code == 1, (
        f"Expected exit 1 for naked broken import, got {exit_code}. stdout data: {data}"
    )
    assert len(data.get("broken_unprotected", [])) > 0, (
        "Expected non-empty broken_unprotected list"
    )
    # Confirm the entry references the right file/module
    entry = data["broken_unprotected"][0]
    assert "core.nonexistent_module_xyz" in entry["import_str"] or \
           "core.nonexistent_module_xyz" == entry["module"]
    assert entry["protected"] is False


# ---------------------------------------------------------------------------
# Test 2: protected broken import → exit 0
# ---------------------------------------------------------------------------

def test_broken_protected_exits_0(tmp_path: Path) -> None:
    """A broken import guarded by try/except ImportError must cause exit 0."""
    _make_internal_dir(tmp_path, "core")

    guarded = tmp_path / "mymodule_guarded.py"
    guarded.write_text(
        textwrap.dedent("""\
            try:
                from core.nonexistent_protected_xyz import Thing
            except ImportError:
                Thing = None
        """),
        encoding="utf-8",
    )

    exit_code, data = _run(tmp_path)

    assert exit_code == 0, (
        f"Expected exit 0 for protected broken import, got {exit_code}. data: {data}"
    )
    assert len(data.get("broken_unprotected", [])) == 0, (
        "broken_unprotected must be empty for a protected import"
    )
    assert len(data.get("broken_protected", [])) > 0, (
        "broken_protected must have at least one entry"
    )
    entry = data["broken_protected"][0]
    assert entry["protected"] is True


# ---------------------------------------------------------------------------
# Test 3: test files are ignored
# ---------------------------------------------------------------------------

def test_test_files_are_ignored(tmp_path: Path) -> None:
    """Broken import in a test_ file goes to ignored_tests, not broken lists."""
    _make_internal_dir(tmp_path, "core")

    test_file = tmp_path / "test_something.py"
    test_file.write_text(
        textwrap.dedent("""\
            from core.some_nonexistent_module_abc import Foo
        """),
        encoding="utf-8",
    )

    exit_code, data = _run(tmp_path)

    assert exit_code == 0, (
        f"Expected exit 0 when broken import is in test file, got {exit_code}. data: {data}"
    )
    assert len(data.get("broken_unprotected", [])) == 0, (
        "broken_unprotected must be empty for test files"
    )
    assert len(data.get("broken_protected", [])) == 0, (
        "broken_protected must be empty for test files"
    )
    assert len(data.get("ignored_tests", [])) > 0, (
        "ignored_tests must have at least one entry"
    )
    entry = data["ignored_tests"][0]
    assert entry.get("reason") == "test file"


# ---------------------------------------------------------------------------
# Test 4: ratchet — no new broken unprotected imports in the real repo
# ---------------------------------------------------------------------------

def test_kernel_boundary_not_weakened() -> None:
    """Ratchet: no file outside tests/ and scripts/ has a broken unprotected import.

    This test documents the current state of the repo. If new broken internal
    imports are introduced in non-test, non-script files, this test will fail
    loudly, as intended.
    """
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo_root)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    stdout = result.stdout.strip()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Script produced non-JSON output. returncode={result.returncode}\n"
            f"stdout={stdout[:2000]}\nstderr={result.stderr[:500]}"
        )

    broken_unprotected: list[dict] = data.get("broken_unprotected", [])

    # Entries that are in tests/ or scripts/ are acceptable (test/tool files)
    allowed_prefixes = ("tests/", "scripts/")
    unexpected = [
        entry
        for entry in broken_unprotected
        if not any(entry["file"].startswith(p) for p in allowed_prefixes)
    ]

    if unexpected:
        lines = [
            f"  {e['file']}:{e['line']}  {e['import_str']}"
            for e in unexpected
        ]
        pytest.fail(
            f"Found {len(unexpected)} broken unprotected import(s) in non-test/non-script files.\n"
            "These are import boundary violations that must be fixed:\n"
            + "\n".join(lines)
        )
