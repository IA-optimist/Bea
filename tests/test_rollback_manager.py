"""Tests for core/rollback_manager.py — file backup and restore."""
import os
import tempfile
from pathlib import Path
_silent_log = __import__("structlog").get_logger(__name__)


def test_import():
    from core.rollback_manager import (
        RollbackManager, RollbackContext,
        backup_file, restore_file, restore_latest,
        save_diff, list_backups, get_rollback_manager,
    )


def test_backup_nonexistent_file():
    from core.rollback_manager import backup_file
    result = backup_file("/nonexistent_path_12345/missing.py")
    assert result is None


def test_backup_and_restore():
    from core.rollback_manager import backup_file, restore_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("original content")
        path = f.name
    try:
        backup_path = backup_file(path)
        assert backup_path is not None
        assert backup_path.exists()
        # Overwrite original
        Path(path).write_text("modified content")
        assert Path(path).read_text() == "modified content"
        # Restore
        ok = restore_file(path, backup_path)
        assert ok
        assert Path(path).read_text() == "original content"
    finally:
        os.unlink(path)
        if backup_path and backup_path.exists():
            backup_path.unlink()


def test_save_diff():
    from core.rollback_manager import save_diff
    diff_path = save_diff("/tmp/test.py", "old line\n", "new line\n")
    if diff_path:
        content = diff_path.read_text()
        assert "old line" in content or "new line" in content
        diff_path.unlink(missing_ok=True)


def test_save_diff_no_changes():
    from core.rollback_manager import save_diff
    result = save_diff("/tmp/test.py", "same\n", "same\n")
    assert result is None  # no diff to save


def test_list_backups_empty():
    from core.rollback_manager import list_backups
    result = list_backups("/nonexistent_unique_path_12345.py")
    assert result == []


def test_rollback_context_success():
    from core.rollback_manager import RollbackContext
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("content")
        path = f.name
    try:
        with RollbackContext(path) as ctx:
            Path(path).write_text("new content")
        # No exception → file keeps new content
        assert Path(path).read_text() == "new content"
    finally:
        os.unlink(path)


def test_rollback_context_on_error():
    from core.rollback_manager import RollbackContext
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("original")
        path = f.name
    try:
        try:
            with RollbackContext(path) as ctx:
                Path(path).write_text("broken")
                raise RuntimeError("simulated failure")
        except RuntimeError:
            _silent_log.debug("suppressed_exception", src='test_rollback_manager.py')
        # Exception → file should be restored
        assert Path(path).read_text() == "original"
    finally:
        os.unlink(path)


def test_get_rollback_manager_singleton():
    from core.rollback_manager import get_rollback_manager
    m1 = get_rollback_manager()
    m2 = get_rollback_manager()
    assert m1 is m2


def test_restore_latest_no_backups():
    from core.rollback_manager import restore_latest
    result = restore_latest("/nonexistent_path_99999.py")
    assert result is False
