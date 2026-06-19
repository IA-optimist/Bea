from __future__ import annotations

# Re-export SQLite helpers from core/db.py for backward compatibility
# (core/db/ directory shadows core/db.py - this bridges the gap)
import importlib.util
import os

_db_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db.py")
if os.path.exists(_db_py):
    _spec = importlib.util.spec_from_file_location("core._db_sqlite", _db_py)
    assert _spec is not None
    assert _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    # Re-export all public symbols
    get_db = _mod.get_db
    execute = _mod.execute
    fetchall = _mod.fetchall
    fetchone = _mod.fetchone
    dumps = _mod.dumps
    loads = _mod.loads
    get_sqlite_path = _mod.get_sqlite_path
    reset_singleton = _mod.reset_singleton
