"""
tests/test_performance_persistence.py — Kernel performance persistence tests.

Validates:
  - PerformanceRecord serialization round-trip
  - PerformanceStore save/load from file
  - Boot-time restoration of performance data
  - Merge semantics (more observations wins)
  - Missing/corrupt file handling (fail-open)
  - Periodic save via snapshot loop
  - Shutdown save hook
"""
import json
import os
import tempfile
import time

from kernel.capabilities.performance import (
    PerformanceStore, PerformanceRecord,
)


class TestRecordSerialization:

    def test_PP01_to_persistent_dict(self):
        """PerformanceRecord serializes to persistent dict."""
        record = PerformanceRecord(entity_id="test_tool", entity_type="tool")
        for _ in range(5):
            record.record_outcome(True, duration_ms=100)
        record.record_outcome(False, duration_ms=200)

        d = record.to_persistent_dict()
        assert d["entity_id"] == "test_tool"
        assert d["entity_type"] == "tool"
        assert d["total"] == 6
        assert d["successes"] == 5
        assert d["failures"] == 1
        assert d["total_duration_ms"] == 700
        assert len(d["recent"]) == 6
        assert d["ema_success"] < 1.0  # not perfect
        assert d["first_seen"] > 0
        assert d["last_seen"] > 0

    def test_PP02_roundtrip(self):
        """Record survives serialization → deserialization round-trip."""
        original = PerformanceRecord(entity_id="roundtrip", entity_type="provider")
        for i in range(10):
            original.record_outcome(i % 3 != 0, duration_ms=50 + i * 10)

        d = original.to_persistent_dict()
        restored = PerformanceRecord.from_persistent_dict(d)

        assert restored.entity_id == original.entity_id
        assert restored.entity_type == original.entity_type
        assert restored.total == original.total
        assert restored.successes == original.successes
        assert restored.failures == original.failures
        assert abs(restored.ema_success - original.ema_success) < 0.001
        assert len(restored._recent) == len(original._recent)
        assert abs(restored.total_duration_ms - original.total_duration_ms) < 0.01

    def test_PP03_inf_min_duration(self):
        """Record with no duration observations serializes min_duration as None."""
        record = PerformanceRecord(entity_id="x", entity_type="tool")
        d = record.to_persistent_dict()
        assert d["min_duration_ms"] is None
        restored = PerformanceRecord.from_persistent_dict(d)
        assert restored.min_duration_ms == float("inf")

    def test_PP04_empty_recent(self):
        """Record with no observations has empty recent list."""
        d = {"entity_id": "x", "entity_type": "tool", "total": 0, "successes": 0,
             "failures": 0, "ema_success": 0.5, "recent": []}
        record = PerformanceRecord.from_persistent_dict(d)
        assert record._recent == []
        assert record.total == 0


class TestStorePersistence:

    def test_PP05_save_creates_file(self):
        """save_to_file creates a valid JSON file."""
        store = PerformanceStore()
        for _ in range(5):
            store.record_tool_outcome("t1", True)
        store.record_tool_outcome("t2", False)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            ok = store.save_to_file(path)
            assert ok is True
            assert os.path.exists(path)

            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["version"] == 1
            assert data["record_count"] == 2
            assert "tool:t1" in data["records"]
            assert "tool:t2" in data["records"]
        finally:
            os.unlink(path)

    def test_PP06_load_restores_records(self):
        """load_from_file restores records into an empty store."""
        store1 = PerformanceStore()
        for _ in range(8):
            store1.record_tool_outcome("persistent", True, provider_id="prov_a")
        store1.record_tool_outcome("persistent", False, provider_id="prov_a")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store1.save_to_file(path)

            store2 = PerformanceStore()
            loaded = store2.load_from_file(path)
            assert loaded == 2  # tool:persistent + provider:prov_a

            perf = store2.get_tool_performance("persistent")
            assert perf is not None
            assert perf["total"] == 9
            assert perf["successes"] == 8
        finally:
            os.unlink(path)

    def test_PP07_load_skips_existing(self):
        """load_from_file doesn't overwrite in-memory records."""
        store1 = PerformanceStore()
        for _ in range(10):
            store1.record_tool_outcome("overlap", True)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store1.save_to_file(path)

            store2 = PerformanceStore()
            # Add fresh data to store2 before loading
            for _ in range(3):
                store2.record_tool_outcome("overlap", False)

            loaded = store2.load_from_file(path)
            assert loaded == 0  # tool:overlap already exists → skipped

            # Should keep the runtime (3 obs) not the disk (10 obs)
            perf = store2.get_tool_performance("overlap")
            assert perf["total"] == 3
        finally:
            os.unlink(path)

    def test_PP08_merge_keeps_larger(self):
        """merge_from_file keeps the record with more observations."""
        store1 = PerformanceStore()
        for _ in range(20):
            store1.record_tool_outcome("big", True)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store1.save_to_file(path)

            store2 = PerformanceStore()
            for _ in range(3):
                store2.record_tool_outcome("big", False)

            merged = store2.merge_from_file(path)
            assert merged == 1  # disk has 20 > runtime's 3

            perf = store2.get_tool_performance("big")
            assert perf["total"] == 20
        finally:
            os.unlink(path)

    def test_PP09_missing_file_returns_zero(self):
        """Loading from nonexistent file returns 0, no crash."""
        store = PerformanceStore()
        loaded = store.load_from_file("/tmp/nonexistent_perf_abc.json")
        assert loaded == 0

    def test_PP10_corrupt_file_returns_zero(self):
        """Loading from corrupt file returns 0, no crash."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("NOT VALID JSON {{{")
            path = f.name
        try:
            store = PerformanceStore()
            loaded = store.load_from_file(path)
            assert loaded == 0
        finally:
            os.unlink(path)

    def test_PP11_wrong_version_skipped(self):
        """File with unknown version is skipped."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"version": 99, "records": {}}, f)
            path = f.name
        try:
            store = PerformanceStore()
            loaded = store.load_from_file(path)
            assert loaded == 0
        finally:
            os.unlink(path)

    def test_PP12_atomic_write(self):
        """Save uses atomic write (no .tmp left behind)."""
        store = PerformanceStore()
        store.record_tool_outcome("atomic", True)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store.save_to_file(path)
            assert os.path.exists(path)
            assert not os.path.exists(path + ".tmp")
        finally:
            os.unlink(path)


class TestBootIntegration:

    def test_PP13_boot_loads_performance(self):
        """Kernel boot loads persisted performance data."""
        import inspect
        from kernel.runtime.boot import boot_kernel
        source = inspect.getsource(boot_kernel)
        assert "_load_performance" in source

    def test_PP14_save_performance_function(self):
        """save_performance() exported from boot module."""
        from kernel.runtime.boot import save_performance
        # Should not crash even if no runtime booted
        result = save_performance()
        # Result depends on whether runtime is initialized
        assert isinstance(result, bool)

    def test_PP15_boot_restore_roundtrip(self):
        """Performance data survives save → boot cycle."""

        # Create store with data
        store = PerformanceStore()
        for _ in range(10):
            store.record_tool_outcome("survived", True, provider_id="prov_x")
        store.record_tool_outcome("survived", False, provider_id="prov_x")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store.save_to_file(path)

            # Simulate boot: new empty store + load
            new_store = PerformanceStore()
            new_store.load_from_file(path)

            perf = new_store.get_tool_performance("survived")
            assert perf is not None
            assert perf["total"] == 11
            assert perf["successes"] == 10
            assert abs(perf["success_rate"] - 10/11) < 0.01
        finally:
            os.unlink(path)


class TestShutdownIntegration:

    def test_PP16_shutdown_hook_exists(self):
        """API shutdown handler calls save_performance."""
        import inspect
        # Find the shutdown handler in api.main
        import importlib
        main_mod = importlib.import_module("api.main")
        source = inspect.getsource(main_mod)
        assert "save_performance" in source
        assert "lifespan" in source and "_on_shutdown" in source

    def test_PP17_snapshot_loop_saves_periodically(self):
        """Metrics bridge snapshot loop includes kernel performance save."""
        import inspect
        from core.metrics_bridge import _snapshot_loop
        source = inspect.getsource(_snapshot_loop)
        assert "save_performance" in source


class TestEdgeCases:

    def test_PP18_save_empty_store(self):
        """Saving an empty store works."""
        store = PerformanceStore()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            ok = store.save_to_file(path)
            assert ok is True
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["record_count"] == 0
        finally:
            os.unlink(path)

    def test_PP19_load_empty_file(self):
        """Loading from a file with no records works."""
        data = {"version": 1, "saved_at": time.time(), "record_count": 0, "records": {}}
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            store = PerformanceStore()
            loaded = store.load_from_file(path)
            assert loaded == 0
        finally:
            os.unlink(path)

    def test_PP20_concurrent_save_load(self):
        """Save and load are thread-safe."""
        import threading
        store = PerformanceStore()
        for _ in range(50):
            store.record_tool_outcome("concurrent", True)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        errors = []
        def save():
            try:
                store.save_to_file(path)
            except Exception as e:
                errors.append(e)

        def load():
            try:
                store2 = PerformanceStore()
                store2.load_from_file(path)
            except Exception as e:
                errors.append(e)

        try:
            threads = [threading.Thread(target=save) for _ in range(3)]
            threads += [threading.Thread(target=load) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)
            assert len(errors) == 0, f"Thread errors: {errors}"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_PP21_partial_record_in_file(self):
        """File with partially valid records loads what it can."""
        data = {
            "version": 1,
            "saved_at": time.time(),
            "record_count": 2,
            "records": {
                "tool:good": {
                    "entity_id": "good", "entity_type": "tool",
                    "total": 5, "successes": 4, "failures": 1,
                    "ema_success": 0.8, "recent": [True, True, True, True, False],
                },
                "tool:bad": "not a dict",  # corrupt record
            },
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            store = PerformanceStore()
            loaded = store.load_from_file(path)
            assert loaded == 1  # only good record loaded
            assert store.get_tool_performance("good") is not None
        finally:
            os.unlink(path)

    def test_PP22_ema_preserves_precision(self):
        """EMA is serialized with enough precision."""
        record = PerformanceRecord(entity_id="precise", entity_type="tool")
        # Create a specific EMA value
        for i in range(20):
            record.record_outcome(i % 5 != 0)

        d = record.to_persistent_dict()
        restored = PerformanceRecord.from_persistent_dict(d)
        assert abs(restored.ema_success - record.ema_success) < 1e-5

    def test_PP23_timestamps_preserved(self):
        """First/last seen timestamps survive round-trip."""
        record = PerformanceRecord(entity_id="ts", entity_type="provider")
        record.record_outcome(True)
        time.sleep(0.01)
        record.record_outcome(False)

        d = record.to_persistent_dict()
        restored = PerformanceRecord.from_persistent_dict(d)
        assert restored.first_seen == record.first_seen
        assert restored.last_seen == record.last_seen
        assert restored.last_success == record.last_success
        assert restored.last_failure == record.last_failure

    def test_PP24_recent_window_capped(self):
        """Restored record recent window respects _RECENT_WINDOW cap."""
        from kernel.capabilities.performance import _RECENT_WINDOW
        d = {
            "entity_id": "capped", "entity_type": "tool",
            "total": 100, "successes": 80, "failures": 20,
            "ema_success": 0.7,
            "recent": [True] * (_RECENT_WINDOW + 20),  # over limit
        }
        restored = PerformanceRecord.from_persistent_dict(d)
        assert len(restored._recent) == _RECENT_WINDOW

    def test_PP25_save_creates_parent_dirs(self):
        """save_to_file creates parent directories."""
        import shutil
        tmpdir = tempfile.mkdtemp()
        nested_path = os.path.join(tmpdir, "deep", "nested", "perf.json")
        try:
            store = PerformanceStore()
            store.record_tool_outcome("nested", True)
            ok = store.save_to_file(nested_path)
            assert ok is True
            assert os.path.exists(nested_path)
        finally:
            shutil.rmtree(tmpdir)
