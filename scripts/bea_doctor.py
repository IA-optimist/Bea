"""Béa doctor: readiness gates for local dev, private beta, and public beta.

Fail-closed diagnostic report with human-readable and JSON output.
The doctor does not try to make the project beta-ready; it reports truthfully.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEXT_EXTS = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".sh", ".ps1", ".js", ".ts", ".tsx", ".html"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", "storage", "workspace", "logs", ".qdrant-initialized"}
SKIP_SUBSTRINGS = (".git", ".venv", "venv", "node_modules", "storage/", ".qdrant")
ALLOWED_SECRET_PATHS = {
    ".env.example",
    ".env.production.example",
    ".gitleaks.toml",
    ".secrets.baseline",
}

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sk-", re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b")),
    ("ghp_", re.compile(r"\b(ghp_[a-zA-Z0-9]{36,})\b")),
    ("github_pat_", re.compile(r"\b(github_pat_[a-zA-Z0-9_=-]{16,})\b", re.I)),
    ("gho_", re.compile(r"\b(gho_[a-zA-Z0-9]{36,})\b")),
    ("glpat-", re.compile(r"\b(glpat-[a-zA-Z0-9_\-]{20,})\b")),
    ("xoxb-", re.compile(r"\b(xoxb-[a-zA-Z0-9_\-]{10,})\b")),
    ("AKIA", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("private key", re.compile(r"BEGIN PRIVATE KEY")),
]
_PLACEHOLDER_RE = re.compile(r"^(CHANGE_ME|YOUR_KEY|REPLACE_ME|sk-CHANGE_ME|jv-CHANGE_ME|test-secret|example|placeholder).*$", re.I)
_PUBLIC_BETA_TRUE_RE = re.compile(
    r"\b(?:ready\s+for\s+public\s+beta|public\s+beta\s+ready|"
    r"status\s*:\s*public\s+beta|ready_for_public_beta\s*:\s*true)\b",
    re.I,
)
_PUBLIC_BETA_FALSE_RE = re.compile(r"ready_for_public_beta\s*:\s*false", re.I)
_PRIVATE_BETA_RE = re.compile(
    r"\b(?:private beta|developer preview|experimental|not production-ready|not fully autonomous|no-go)\b",
    re.I,
)


@dataclass(frozen=True)
class DoctorCheckResult:
    name: str
    status: str
    details: str = ""
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "details": self.details,
            "evidence": list(self.evidence),
        }


@dataclass
class DoctorReport:
    repo_root: Path
    checks: dict[str, DoctorCheckResult] = field(default_factory=dict)
    local_dev_status: str = "WARN"
    private_beta_status: str = "WARN"
    public_beta_status: str = "FAIL"
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "repo_root": self.repo_root.as_posix(),
            "local_dev": self.local_dev_status,
            "private_beta": self.private_beta_status,
            "public_beta": self.public_beta_status,
            "checks": {name: check.to_dict() for name, check in self.checks.items()},
            "recommendation": self.recommendation,
        }

    def to_text(self) -> str:
        lines = [
            "Béa Doctor Report",
            "",
            f"Local dev: {self.local_dev_status}",
            f"Private beta: {self.private_beta_status}",
            f"Public beta: {self.public_beta_status}",
            "",
            "Checks:",
        ]
        for name in CHECK_ORDER:
            check = self.checks[name]
            details = f" — {check.details}" if check.details else ""
            lines.append(f"- {name}: {check.status}{details}")
        lines.extend(["", "Recommendation:", self.recommendation or "Review the failing gates above."])
        return "\n".join(lines)


CHECK_ORDER = (
    "public_beta_flag",
    "docs_status_truth",
    "self_improvement_default_off",
    "dangerous_tools_gated",
    "human_approval_path",
    "session_store_safety",
    "memory_privacy_gate",
    "sandbox_boundary",
    "channel_pairing_access_control",
    "secret_hygiene",
    "validation_scripts_present",
    "affect_subsystem_invariants",
)


def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(substr in rel for substr in SKIP_SUBSTRINGS):
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        yield path


def _read_text(root: Path, rel: str) -> str:
    path = root / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _present(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _scan_for_secret_hits(root: Path) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for path in _iter_text_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWED_SECRET_PATHS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for label, pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1) if match.lastindex else match.group(0)
                if value and _PLACEHOLDER_RE.match(value):
                    continue
                if value and any(fake in value.lower() for fake in {"test", "example", "change_me", "placeholder", "fake"}):
                    if len(value) < 40:
                        continue
                hits.append((rel, label))
    return sorted(set(hits))


def _detect_public_state_text(texts: Sequence[str]) -> tuple[bool, bool, list[str], list[str]]:
    positive: list[str] = []
    negative: list[str] = []
    for text in texts:
        for line in text.splitlines():
            if _PUBLIC_BETA_TRUE_RE.search(line):
                positive.append(line.strip())
            if _PUBLIC_BETA_FALSE_RE.search(line) or _PRIVATE_BETA_RE.search(line):
                negative.append(line.strip())
    return bool(positive), bool(negative), positive, negative


def aggregate_tier_status(checks: dict[str, DoctorCheckResult], names: Sequence[str]) -> str:
    statuses = [checks[name].status for name in names if name in checks and checks[name].status != "SKIP"]
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if any(status == "WARN" for status in statuses):
        return "WARN"
    if not statuses:
        return "SKIP"
    return "PASS"


def check_public_beta_flag(repo_root: Path) -> DoctorCheckResult:
    checklist = _read_text(repo_root, "PUBLIC_BETA_CHECKLIST.md")
    readme_beta = _read_text(repo_root, "README_PUBLIC_BETA.md")
    status_doc = _read_text(repo_root, "docs/STATUS.md")
    readme = _read_text(repo_root, "README.md")
    texts = [checklist, readme_beta, status_doc, readme]
    positive, negative, positive_lines, negative_lines = _detect_public_state_text(texts)
    if positive and negative:
        return DoctorCheckResult(
            "public_beta_flag",
            "FAIL",
            "Conflicting public-beta statements found.",
            tuple(positive_lines[:2] + negative_lines[:2]),
        )
    if positive and not negative:
        return DoctorCheckResult("public_beta_flag", "FAIL", "Repo claims public beta readiness without a no-go gate.", tuple(positive_lines[:3]))
    if negative:
        return DoctorCheckResult("public_beta_flag", "PASS", "Repo stays explicitly out of public beta.", tuple(negative_lines[:3]))
    return DoctorCheckResult("public_beta_flag", "WARN", "No explicit public-beta stance found.", ())


def check_docs_status_truth(repo_root: Path) -> DoctorCheckResult:
    texts = [
        _read_text(repo_root, "README.md"),
        _read_text(repo_root, "README_PUBLIC_BETA.md"),
        _read_text(repo_root, "PUBLIC_BETA_CHECKLIST.md"),
        _read_text(repo_root, "docs/STATUS.md"),
    ]
    positive, negative, positive_lines, negative_lines = _detect_public_state_text(texts)
    if positive and negative:
        return DoctorCheckResult(
            "docs_status_truth",
            "FAIL",
            "Main docs contradict each other on public-beta status.",
            tuple(positive_lines[:2] + negative_lines[:2]),
        )
    if negative and not positive:
        return DoctorCheckResult(
            "docs_status_truth",
            "PASS",
            "Main docs consistently frame Béa as private beta / experimental.",
            tuple(negative_lines[:3]),
        )
    if positive:
        return DoctorCheckResult("docs_status_truth", "FAIL", "Docs claim public beta readiness without matching gates.", tuple(positive_lines[:3]))
    return DoctorCheckResult("docs_status_truth", "WARN", "Docs do not make a clear readiness statement.", ())


def check_self_improvement_default_off(repo_root: Path, settings=None) -> DoctorCheckResult:
    try:
        if settings is None:
            from config.settings import get_settings

            settings = get_settings()
    except Exception as exc:
        return DoctorCheckResult("self_improvement_default_off", "WARN", f"Settings unavailable: {exc!s}", ())

    enabled = bool(getattr(settings, "self_improve_enabled", False))
    skip_gate = bool(getattr(settings, "bea_skip_improvement_gate", False))
    if enabled or skip_gate:
        return DoctorCheckResult(
            "self_improvement_default_off",
            "FAIL",
            "Self-improvement is enabled or skip-gated by default.",
            (f"enabled={enabled}", f"skip_gate={skip_gate}"),
        )

    env_example = _read_text(repo_root, ".env.example")
    evidence = ["settings=False/False"]
    if "SELF_IMPROVE_ENABLED=false" in env_example.replace(" ", ""):
        evidence.append(".env.example sets SELF_IMPROVE_ENABLED=false")
    return DoctorCheckResult(
        "self_improvement_default_off",
        "PASS",
        "Self-improvement defaults to off and the skip gate defaults to off.",
        tuple(evidence),
    )


def check_dangerous_tools_gated(repo_root: Path) -> DoctorCheckResult:
    evidence: list[str] = []
    files = {
        "core/tool_executor.py": ("shell_not_allowed", "allowlist"),
        "core/approval_queue.py": ("approval",),
        "executor/supervised_executor.py": ("approval required", "blocked"),
        "core/self_improvement/promotion_pipeline.py": ("DockerSandbox", "REVIEW", "PR"),
        "executor/desktop_env/sandbox.py": ("network_mode=\"none\"", "read_only=True", "cap_drop=[\"ALL\"]"),
        "core/security/secret_policy.py": ("allowlist", "approval"),
        "security/policies/rules.py": ("approval", "self-improvement"),
    }
    hits = 0
    for rel, needles in files.items():
        text = _read_text(repo_root, rel)
        if not text:
            continue
        for needle in needles:
            if needle in text:
                hits += 1
                evidence.append(f"{rel}:{needle}")
                break
    if _present(repo_root, "core/tool_executor.py") and hits >= 4:
        return DoctorCheckResult("dangerous_tools_gated", "PASS", "Dangerous tool paths have visible gates.", tuple(evidence[:8]))
    if hits:
        return DoctorCheckResult("dangerous_tools_gated", "WARN", "Some gates exist, but the coverage is partial.", tuple(evidence[:8]))
    return DoctorCheckResult("dangerous_tools_gated", "FAIL", "No visible gate for dangerous tools.", ())


def check_human_approval_path(repo_root: Path) -> DoctorCheckResult:
    evidence: list[str] = []
    files = [
        "core/approval_queue.py",
        "api/routes/approval.py",
        "executor/supervised_executor.py",
        "tests/test_approval_gate.py",
        "core/self_improvement/human_gate.py",
    ]
    present = [rel for rel in files if _present(repo_root, rel)]
    for rel in present:
        evidence.append(rel)
    if {"core/approval_queue.py", "api/routes/approval.py", "tests/test_approval_gate.py"}.issubset(set(present)):
        return DoctorCheckResult("human_approval_path", "PASS", "Human approval path is implemented and tested.", tuple(evidence))
    if present:
        return DoctorCheckResult("human_approval_path", "WARN", "Human approval path is documented or partially wired.", tuple(evidence))
    return DoctorCheckResult("human_approval_path", "FAIL", "No human approval path found.", ())


def check_session_store_safety(repo_root: Path, settings=None) -> DoctorCheckResult:
    evidence: list[str] = []
    try:
        from core.session_store import InMemorySessionStore, RedisSessionStore, get_session_store

        if settings is None:
            from config.settings import get_settings

            settings = get_settings()
        backend = getattr(settings, "bea_session_store", "")
        redis_url = getattr(settings, "bea_redis_url", "")
        evidence.append(f"backend={backend or 'memory'}")
        if redis_url:
            evidence.append("bea_redis_url=configured")
        store = get_session_store("private_beta", config=settings)
        if isinstance(store, RedisSessionStore):
            return DoctorCheckResult(
                "session_store_safety",
                "WARN",
                "Redis session store is configured for beta/prod profiles; live connectivity is not probed by the doctor.",
                tuple(evidence + ["core/session_store.py"]),
            )
        if isinstance(store, InMemorySessionStore):
            return DoctorCheckResult(
                "session_store_safety",
                "FAIL",
                "Beta/profile selection fell back to InMemorySessionStore, which is not beta-safe.",
                tuple(evidence + ["core/session_store.py"]),
            )
    except Exception as exc:
        return DoctorCheckResult(
            "session_store_safety",
            "FAIL",
            f"No beta-safe session store could be selected: {exc!s}",
            tuple(evidence),
        )

    return DoctorCheckResult(
        "session_store_safety",
        "FAIL",
        "No beta-safe session store could be selected.",
        tuple(evidence),
    )


def check_memory_privacy_gate(repo_root: Path) -> DoctorCheckResult:
    evidence: list[str] = []
    found_script = _present(repo_root, "scripts/audit_memory_store.py")
    found_tests = _present(repo_root, "tests/test_memory_hygiene.py")
    found_privacy_docs = _present(repo_root, "docs/PRIVACY_FOR_TESTERS.md")
    found_sanitizer = _present(repo_root, "core/security/input_sanitizer.py") or _present(repo_root, "executor/output_validator.py")
    found_cleanup = any("cleanup" in rel.lower() for rel in {
        "core/workspace_cleaner.py",
        "core/knowledge/knowledge_cleanup_legacy.py",
        "memory/legacy/store_legacy.py",
    } if _present(repo_root, rel))
    if found_script:
        evidence.append("scripts/audit_memory_store.py")
    if found_tests:
        evidence.append("tests/test_memory_hygiene.py")
    if found_privacy_docs:
        evidence.append("docs/PRIVACY_FOR_TESTERS.md")
    if found_sanitizer:
        evidence.append("sanitizer")
    if found_cleanup:
        evidence.append("cleanup code")

    if found_script and found_tests and found_privacy_docs and found_sanitizer:
        return DoctorCheckResult(
            "memory_privacy_gate",
            "WARN",
            "Memory privacy scripts and sanitizers exist, but cleanup remains a derived/manual surface.",
            tuple(evidence),
        )
    if found_script or found_sanitizer:
        return DoctorCheckResult(
            "memory_privacy_gate",
            "WARN",
            "Some memory privacy machinery exists, but coverage is incomplete.",
            tuple(evidence),
        )
    return DoctorCheckResult("memory_privacy_gate", "FAIL", "No visible memory privacy gate found.", tuple(evidence))


def check_sandbox_boundary(repo_root: Path) -> DoctorCheckResult:
    evidence: list[str] = []
    files = [
        "executor/desktop_env/sandbox.py",
        "core/self_improvement/promotion_pipeline.py",
        "core/self_improvement/git_agent.py",
    ]
    text = ""
    for rel in files:
        if _present(repo_root, rel):
            evidence.append(rel)
            text += "\n" + _read_text(repo_root, rel)
    has_network_none = "network_mode=\"none\"" in text or "network_mode='none'" in text
    has_read_only = "read_only=True" in text
    has_cleanup = "cleanup" in text.lower() or "sync_to_host" in text
    if evidence and has_network_none and has_read_only and has_cleanup:
        return DoctorCheckResult("sandbox_boundary", "PASS", "Sandbox boundary is implemented with hardening hints.", tuple(evidence))
    if evidence:
        return DoctorCheckResult("sandbox_boundary", "WARN", "Sandbox code exists, but hardening evidence is partial.", tuple(evidence))
    return DoctorCheckResult("sandbox_boundary", "FAIL", "No sandbox boundary found.", ())


def check_channel_pairing_access_control(repo_root: Path) -> DoctorCheckResult:
    evidence: list[str] = []
    if _present(repo_root, "core/self_improvement/human_gate.py"):
        evidence.append("core/self_improvement/human_gate.py")
    docs = _read_text(repo_root, "README_PUBLIC_BETA.md") + "\n" + _read_text(repo_root, "docs/STATUS.md")
    has_external_channels = any(term in docs.lower() for term in ("telegram", "slack", "discord", "whatsapp", "signal"))
    pairing_words = "pairing" in docs.lower() or "pairing" in _read_text(repo_root, "core/self_improvement/human_gate.py").lower()
    access_roles = any(term in docs.lower() for term in ("role", "allowlist", "admin", "operator", "tester"))
    if has_external_channels and not pairing_words:
        return DoctorCheckResult(
            "channel_pairing_access_control",
            "FAIL",
            "External channels are present, but no pairing-code / channel-binding gate was found.",
            tuple(evidence[:3]),
        )
    if has_external_channels and pairing_words and access_roles:
        return DoctorCheckResult(
            "channel_pairing_access_control",
            "PASS",
            "External channels appear to have a role-aware control path.",
            tuple(evidence[:3]),
        )
    if has_external_channels:
        return DoctorCheckResult(
            "channel_pairing_access_control",
            "WARN",
            "External channels exist, but pairing/access control could not be proved.",
            tuple(evidence[:3]),
        )
    return DoctorCheckResult("channel_pairing_access_control", "WARN", "No external channel integration was found.", tuple(evidence[:3]))


def check_secret_hygiene(repo_root: Path) -> DoctorCheckResult:
    hits = _scan_for_secret_hits(repo_root)
    real_hits: list[tuple[str, str]] = []
    fixture_hits: list[tuple[str, str]] = []

    for rel, label in hits:
        if rel == "scripts/bea_doctor.py":
            continue
        if rel.startswith("tests/"):
            fixture_hits.append((rel, label))
            continue
        real_hits.append((rel, label))

    if real_hits:
        sample = [f"{rel}:{label}" for rel, label in real_hits[:10]]
        return DoctorCheckResult(
            "secret_hygiene",
            "FAIL",
            "Probable secret-shaped values found in tracked text files.",
            tuple(sample),
        )
    if fixture_hits:
        sample = [f"{rel}:{label}" for rel, label in fixture_hits[:8]]
        return DoctorCheckResult(
            "secret_hygiene",
            "PASS",
            "Only test fixtures / scrubber examples were found; no probable real secrets were detected.",
            tuple(sample),
        )
    return DoctorCheckResult("secret_hygiene", "PASS", "No probable real secrets detected in tracked text files.", ())


def check_validation_scripts_present(repo_root: Path) -> DoctorCheckResult:
    required = [
        "scripts/private_beta_gate.py",
        "scripts/audit_memory_store.py",
        "scripts/verify_boot.sh",
        "scripts/verify_prod.sh",
        "scripts/verify-e2e.sh",
        "validate_p0p1.sh",
    ]
    present = [rel for rel in required if _present(repo_root, rel)]
    missing = [rel for rel in required if rel not in present]
    if len(present) == len(required):
        return DoctorCheckResult("validation_scripts_present", "PASS", "Validation scripts are present.", tuple(present))
    if present:
        return DoctorCheckResult(
            "validation_scripts_present",
            "WARN",
            "Some validation scripts exist, but the requested set is incomplete.",
            tuple(present + missing[:2]),
        )
    return DoctorCheckResult("validation_scripts_present", "FAIL", "No validation scripts were found.", tuple(missing[:3]))


def check_affect_subsystem_invariants(repo_root: Path) -> DoctorCheckResult:
    required = [
        "core/orchestrator_v2.py",
        "core/self_critic.py",
        "tests/core/test_critic_rerun_forcing.py",
        "tests/core/test_critic_pass_forcing_runtime.py",
        "tests/core/test_critic_rerun_log_context.py",
    ]
    missing = [rel for rel in required if not _present(repo_root, rel)]
    if not missing:
        return DoctorCheckResult("affect_subsystem_invariants", "PASS", "Critic rerun invariants and tests are present.", tuple(required))
    if len(missing) < len(required):
        return DoctorCheckResult("affect_subsystem_invariants", "WARN", "Critic rerun invariants are partially present.", tuple(missing))
    return DoctorCheckResult("affect_subsystem_invariants", "FAIL", "Critic rerun invariants were not found.", tuple(missing[:3]))


def _compose_report(repo_root: Path, checks: dict[str, DoctorCheckResult], settings=None) -> DoctorReport:
    local_checks = (
        "public_beta_flag",
        "docs_status_truth",
        "self_improvement_default_off",
        "dangerous_tools_gated",
        "human_approval_path",
        "secret_hygiene",
        "validation_scripts_present",
        "affect_subsystem_invariants",
    )
    private_checks = (
        "public_beta_flag",
        "docs_status_truth",
        "self_improvement_default_off",
        "dangerous_tools_gated",
        "human_approval_path",
        "session_store_safety",
        "memory_privacy_gate",
        "sandbox_boundary",
        "secret_hygiene",
        "validation_scripts_present",
        "affect_subsystem_invariants",
    )
    public_checks = private_checks + ("channel_pairing_access_control",)

    local_status = aggregate_tier_status(checks, local_checks)
    private_status = aggregate_tier_status(checks, private_checks)
    public_status = aggregate_tier_status(checks, public_checks)

    if public_status == "FAIL":
        recommendation = "Public beta is blocked until the failing critical gates are closed."
    elif public_status == "WARN":
        recommendation = "Public beta is not yet provable; close the remaining warnings before promoting."
    else:
        recommendation = "Public beta is supported by the current gates."

    return DoctorReport(
        repo_root=repo_root,
        checks=checks,
        local_dev_status=local_status,
        private_beta_status=private_status,
        public_beta_status=public_status,
        recommendation=recommendation,
    )


def run_doctor(repo_root: Path | str | None = None, settings=None) -> DoctorReport:
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    checks = {
        "public_beta_flag": check_public_beta_flag(root),
        "docs_status_truth": check_docs_status_truth(root),
        "self_improvement_default_off": check_self_improvement_default_off(root, settings),
        "dangerous_tools_gated": check_dangerous_tools_gated(root),
        "human_approval_path": check_human_approval_path(root),
        "session_store_safety": check_session_store_safety(root, settings),
        "memory_privacy_gate": check_memory_privacy_gate(root),
        "sandbox_boundary": check_sandbox_boundary(root),
        "channel_pairing_access_control": check_channel_pairing_access_control(root),
        "secret_hygiene": check_secret_hygiene(root),
        "validation_scripts_present": check_validation_scripts_present(root),
        "affect_subsystem_invariants": check_affect_subsystem_invariants(root),
    }
    return _compose_report(root, checks, settings=settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Béa doctor / beta readiness gate")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = run_doctor()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=True, sort_keys=True))
    else:
        print(report.to_text())

    if report.public_beta_status == "FAIL" or report.local_dev_status == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
