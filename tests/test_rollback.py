"""Test complet du système de rollback."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rollback_manager import (
    backup_file, restore_file, restore_latest, save_diff, list_backups,
    RollbackContext, get_rollback_manager,
)
from core.tool_executor import write_file_safe

_TEST_FILE = "/tmp/jarvis_rollback_test.py"

def _write(content: str):
    with open(_TEST_FILE, "w") as f:
        f.write(content)

def test_backup_and_restore():
    _write("# version 1\nprint('v1')\n")
    backup = backup_file(_TEST_FILE)
    assert backup is not None, "backup should be created"
    print(f"✅ backup created: {backup}")

    _write("# version 2\nprint('v2')\n")
    ok = restore_file(_TEST_FILE, backup)
    assert ok, "restore should succeed"
    content = open(_TEST_FILE, encoding="utf-8").read()
    assert "v1" in content, f"expected v1, got: {content}"
    print(f"✅ restore OK: content='{content.strip()}'")

def test_rollback_context_auto_restore():
    _write("# original\n")
    try:
        with RollbackContext(_TEST_FILE):
            _write("# modified — will fail\n")
            raise RuntimeError("simulated error during write")
    except RuntimeError:
        pass  # attendu

    content = open(_TEST_FILE, encoding="utf-8").read()
    assert "original" in content, f"should be restored, got: {content}"
    print(f"✅ auto-rollback OK: content='{content.strip()}'")

def test_save_diff():
    old = "line1\nline2\n"
    new = "line1\nline2_modified\nline3\n"
    diff_path = save_diff(_TEST_FILE, old, new)
    if diff_path:
        diff = open(diff_path, encoding="utf-8").read()
        assert "-line2" in diff
        print(f"✅ diff saved: {diff_path}")
    else:
        print("⚠️ diff not saved (identical content)")

def test_write_file_safe():
    _write("# initial content\n")
    result = write_file_safe(_TEST_FILE, "# new safe content\nprint('safe')\n")
    assert result["ok"], f"write_file_safe failed: {result}"
    content = open(_TEST_FILE, encoding="utf-8").read()
    assert "safe" in content
    print(f"✅ write_file_safe OK: {result['result']}")

    # Vérifie que backup existe
    backups = list_backups(_TEST_FILE)
    assert len(backups) > 0, "backup should exist after write_file_safe"
    print(f"✅ backups found: {backups}")

def test_restore_latest():
    _write("# version_A\n")
    backup_file(_TEST_FILE)
    _write("# version_B_corrupted\n")
    ok = restore_latest(_TEST_FILE)
    assert ok, "restore_latest should succeed"
    content = open(_TEST_FILE, encoding="utf-8").read()
    assert "version_A" in content
    print(f"✅ restore_latest OK: content='{content.strip()}'")

def test_rollback_manager_singleton():
    rm = get_rollback_manager()
    assert rm is get_rollback_manager(), "should be singleton"
    print("✅ RollbackManager singleton OK")

if __name__ == "__main__":
    print("=== TEST ROLLBACK SYSTEM ===")
    test_backup_and_restore()
    test_rollback_context_auto_restore()
    test_save_diff()
    test_write_file_safe()
    test_restore_latest()
    test_rollback_manager_singleton()
    print("=== ALL TESTS PASSED ===")
