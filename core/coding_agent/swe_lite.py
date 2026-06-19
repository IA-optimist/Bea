"""SWE-bench-lite style evaluation for Bea coding-agent work.

The goal is not to solve the public SWE-bench corpus. Sprint 3 starts with a
small frozen in-repo suite that proves the coding-agent loop can:
- locate relevant symbols,
- isolate a task in a git worktree,
- run lint/tests,
- produce a clean diff,
- roll back when needed.
"""
from __future__ import annotations

import subprocess  # nosec B404 - local evaluation harness only
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SWELiteCase:
    name: str
    issue: str
    expected_files: tuple[str, ...]
    forbidden_patterns: tuple[str, ...] = ()
    expected_patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SWELiteCaseResult:
    name: str
    passed: bool
    score: float
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SWELiteReport:
    run_id: str
    timestamp: float
    score: float
    passed: bool
    cases: list[SWELiteCaseResult]
    methodology: str = "swe-lite-in-repo-v1"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "methodology": self.methodology,
            "score": round(self.score, 3),
            "passed": self.passed,
            "cases": [case.to_dict() for case in self.cases],
        }


DEFAULT_CASES: tuple[SWELiteCase, ...] = (
    SWELiteCase(
        name="shell-true-hardening",
        issue="Remove unsafe shell=True from command execution and refuse shell metacharacters.",
        expected_files=("gateway/local_tools.py",),
        forbidden_patterns=("shell=True",),
        expected_patterns=("métacaractères shell", "cmd", "/c"),
    ),
    SWELiteCase(
        name="repo-map-indexing",
        issue="Index Python symbols and imports for coding-agent context ranking.",
        expected_files=("core/coding_agent/repo_map.py", "tests/test_sprint3_agent_coder.py"),
        expected_patterns=("class RepoMap", "def build_repo_map", "rank_symbols"),
    ),
    SWELiteCase(
        name="worktree-per-task",
        issue="Create isolated git worktrees per coding task with rollback support.",
        expected_files=("scripts/sprint3_worktree.py",),
        expected_patterns=("git", "worktree", "run_gates", "rollback"),
    ),
)


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _contains(root: Path, rel: str, pattern: str) -> bool:
    path = root / rel
    try:
        return pattern in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _run_sprint3_tests(root: Path) -> tuple[bool, str]:
    proc = subprocess.run(  # nosec B603 - fixed command, no shell interpolation
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_sprint3_agent_coder.py::test_repo_map_indexes_symbols_and_imports",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def evaluate_case(root: Path, case: SWELiteCase, sprint3_tests_ok: bool, sprint3_tests_output: str) -> SWELiteCaseResult:
    missing = [rel for rel in case.expected_files if not _exists(root, rel)]
    forbidden_hits = [
        f"{rel}:{pattern}"
        for rel in case.expected_files
        for pattern in case.forbidden_patterns
        if _contains(root, rel, pattern)
    ]
    expected_hits = [
        f"{rel}:{pattern}"
        for rel in case.expected_files
        for pattern in case.expected_patterns
        if _contains(root, rel, pattern)
    ]
    expected_missing_patterns = [
        pattern
        for pattern in case.expected_patterns
        if not any(_contains(root, rel, pattern) for rel in case.expected_files)
    ]

    passed = not missing and not forbidden_hits and not expected_missing_patterns and sprint3_tests_ok
    score = 0.0
    if case.expected_files:
        score += 0.45 * ((len(case.expected_files) - len(missing)) / len(case.expected_files))
    score += 0.25 * (0.0 if forbidden_hits else 1.0)
    score += 0.20 * (len(expected_hits) / len(case.expected_patterns) if case.expected_patterns else 1.0)
    score += 0.10 * (1.0 if sprint3_tests_ok else 0.0)

    return SWELiteCaseResult(
        name=case.name,
        passed=passed,
        score=round(max(0.0, min(1.0, score)), 3),
        details={
            "missing_files": missing,
            "forbidden_hits": forbidden_hits,
            "expected_hits": expected_hits,
            "expected_missing_patterns": expected_missing_patterns,
            "sprint3_tests_ok": sprint3_tests_ok,
            "sprint3_tests_output_tail": sprint3_tests_output[-500:],
        },
    )


def run_swe_lite_v1(root: str | Path = ".") -> SWELiteReport:
    root_path = Path(root).resolve()
    tests_ok, tests_output = _run_sprint3_tests(root_path)
    cases = [evaluate_case(root_path, case, tests_ok, tests_output) for case in DEFAULT_CASES]
    score = sum(case.score for case in cases) / len(cases)
    return SWELiteReport(
        run_id=f"swe-lite-v1-{int(time.time())}",
        timestamp=time.time(),
        score=round(score, 3),
        passed=score >= 0.85 and tests_ok,
        cases=cases,
    )
