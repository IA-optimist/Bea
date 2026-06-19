"""Architecture test for kernel import boundaries."""
from __future__ import annotations

from pathlib import Path

from scripts import check_kernel_import_boundaries as boundary_check


def test_kernel_import_boundaries_pass_on_repo() -> None:
    assert boundary_check.main() == 0


def test_kernel_import_boundaries_detect_violation(tmp_path: Path, monkeypatch) -> None:
    kernel_root = tmp_path / "kernel"
    kernel_root.mkdir()
    (kernel_root / "bad.py").write_text("import core.tool_executor\n", encoding="utf-8")

    monkeypatch.setattr(boundary_check, "KERNEL_ROOT", kernel_root)
    assert boundary_check.main() == 1
