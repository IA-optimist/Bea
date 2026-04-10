# Legacy Memory Files — JarvisMax

**STATUS:** ⚠️ DEPRECATED — No longer used in production

These files have been moved to `memory/legacy/` as they are no longer imported in the codebase (core/ or api/).

---

## Files in This Directory

| File | Lines | Last Used | Reason for Deprecation |
|------|-------|-----------|------------------------|
| **store_legacy.py** | 377 | Unknown | Replaced by vault_memory.py + postgres_backend.py |
| **patch_memory.py** | 225 | Unknown | Patch tracking not integrated in production |
| **project_memory.py** | 285 | Unknown | Project-scoped wrapper unused (vault_memory sufficient) |
| **failure_memory.py** | ? | Unknown | Failure tracking now in vault_memory |

---

## Migration Path

If you need functionality from these files:

### store_legacy.py → Use vault_memory.py
```python
# OLD
from memory.store_legacy import MemoryStore
store = MemoryStore()
await store.store(key, value, tags)

# NEW
from memory.vault_memory import VaultMemory
vm = VaultMemory()
vm.store(key, value, tags, entry_type="fact")
```

### patch_memory.py → Use vault_memory.py
```python
# OLD
from memory.patch_memory import PatchMemory
pm = PatchMemory()
pm.record_success(patch, model)

# NEW
from memory.vault_memory import VaultMemory
vm = VaultMemory()
vm.store(
    key=f"patch_{hash}",
    value={"patch": patch, "model": model},
    tags=["patch", "success"],
    entry_type="patch"
)
```

### project_memory.py → Use vault_memory.py with tags
```python
# OLD
from memory.project_memory import ProjectMemory
pm = ProjectMemory(project_id="proj_123")
pm.store(key, value)

# NEW
from memory.vault_memory import VaultMemory
vm = VaultMemory()
vm.store(
    key=key,
    value=value,
    tags=["project:proj_123"],
    entry_type="project"
)
```

### failure_memory.py → Use vault_memory.py
```python
# OLD
from memory.failure_memory import FailureMemory
fm = FailureMemory()
fm.record_failure(error, context)

# NEW
from memory.vault_memory import VaultMemory
vm = VaultMemory()
vm.store(
    key=f"failure_{timestamp}",
    value={"error": error, "context": context},
    tags=["failure"],
    entry_type="failure"
)
```

---

## Removal Timeline

- **Session 6 (2026-04-10):** Files moved to legacy/ (import audit completed)
- **Week 2:** Deprecation warnings added to imports (if any emerge)
- **Week 3-4:** Final review for any hidden imports
- **Month 2:** Permanent removal if no production usage confirmed

---

## Restoring a File

If you discover a file is still needed:

```bash
cd ~/Jarvismax-master
git mv memory/legacy/<file>.py memory/
git commit -m "restore: Move <file> back to memory/ (production usage found)"
```

---

**Audit Date:** 2026-04-10  
**Audited By:** Hermes (Session 6-7)  
**Import Count:** 0 for all files (verified in core/ + api/)
