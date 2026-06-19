"""
core/self_improvement/build_digest.py — Reproducible build digest (T4.5).

Computes a deterministic fingerprint of the build inputs (requirements,
pyproject.toml, Python version) so the same patch always produces the
same result across CI and local replay. The digest is stored alongside
every patch record in the improvement history.
"""
from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path

_KEY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
)


def compute_build_digest(repo_root: "Path | str | None" = None) -> dict:
    """
    Fingerprint the current build environment.

    Returns:
        dict with keys:
            python    — "3.11.9" version string
            platform  — "Windows" | "Linux" | "Darwin"
            files     — {filename: sha256_hex[:16]} for pinned build files
            digest    — short combined sha256 of all file contents
    """
    root = Path(repo_root) if repo_root else Path.cwd()

    file_digests: dict[str, str] = {}
    combined_parts: list[str] = []

    for fname in _KEY_FILES:
        p = root / fname
        if p.exists():
            try:
                content = p.read_bytes()
            except OSError:
                continue
            h = hashlib.sha256(content).hexdigest()[:16]
            file_digests[fname] = h
            combined_parts.append(f"{fname}={h}")

    if combined_parts:
        combined_hash = hashlib.sha256("|".join(combined_parts).encode()).hexdigest()[:16]
    else:
        combined_hash = "no_build_files"

    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system(),
        "files": file_digests,
        "digest": combined_hash,
    }
