"""memory_toolkit — stockage et recherche de solutions/erreurs dans Qdrant."""
from __future__ import annotations
import random
import time

QDRANT_URL = "http://qdrant:6333"
COLLECTION = "jarvis_solutions"
_VECTOR_DIM = 768


def _ok(output: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _err(error: str, logs: list = None, risk_level: str = "low", **extra) -> dict:
    base = {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }
    base.update(extra)
    return base


def _pseudo_vector(text: str) -> list[float]:
    """Vecteur pseudo-aléatoire déterministe basé sur hash(text)."""
    seed = hash(text) % (2 ** 32)
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(_VECTOR_DIM)]


def _ensure_solutions_collection() -> bool:
    """Crée la collection jarvis_solutions si elle n'existe pas."""
    try:
        import requests as _req
        r = _req.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=3)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            payload = {"vectors": {"size": _VECTOR_DIM, "distance": "Cosine"}}
            cr = _req.put(f"{QDRANT_URL}/collections/{COLLECTION}", json=payload, timeout=5)
            return cr.status_code in (200, 201)
        return False
    except Exception:
        return False


def _upsert_point(point_id: int, vector: list[float], payload: dict) -> bool:
    try:
        import requests as _req
        body = {"points": [{"id": point_id, "vector": vector, "payload": payload}]}
        r = _req.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json=body, timeout=5
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def memory_store_solution(problem: str, solution: str, tags: list = None) -> dict:
    """Stocke un couple problème/solution dans Qdrant."""
    try:
        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")
        vector = _pseudo_vector(problem)
        point_id = abs(hash(problem + solution)) % (2 ** 31)
        payload = {
            "type": "solution",
            "problem": problem[:500],
            "solution": solution[:500],
            "tags": tags or [],
            "timestamp": time.time(),
        }
        ok = _upsert_point(point_id, vector, payload)
        if ok:
            return _ok(f"stored solution id={point_id}", logs=[f"upsert id={point_id}"])
        return _err("upsert_failed")
    except Exception as e:
        return _err(str(e))


def memory_store_error(error_type: str, context: str, fix: str = "") -> dict:
    """Stocke une erreur + fix éventuel dans Qdrant."""
    try:
        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")
        text = f"{error_type}: {context}"
        vector = _pseudo_vector(text)
        point_id = abs(hash(text + fix)) % (2 ** 31)
        payload = {
            "type": "error",
            "error_type": error_type,
            "context": context[:500],
            "fix": fix[:500],
            "timestamp": time.time(),
        }
        ok = _upsert_point(point_id, vector, payload)
        if ok:
            return _ok(f"stored error id={point_id}", logs=[f"upsert id={point_id}"])
        return _err("upsert_failed")
    except Exception as e:
        return _err(str(e))


def memory_store_patch(filename: str, description: str, diff: str) -> dict:
    """Stocke un patch (diff) en mémoire Qdrant."""
    try:
        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")
        text = f"patch:{filename} {description}"
        vector = _pseudo_vector(text)
        point_id = abs(hash(text + diff[:100])) % (2 ** 31)
        payload = {
            "type": "patch",
            "filename": filename,
            "description": description[:300],
            "diff": diff[:1000],
            "timestamp": time.time(),
        }
        ok = _upsert_point(point_id, vector, payload)
        if ok:
            return _ok(f"stored patch id={point_id}", logs=[f"upsert id={point_id}"])
        return _err("upsert_failed")
    except Exception as e:
        return _err(str(e))


def memory_search_similar(query: str, top_k: int = 3) -> dict:
    """Recherche les solutions similaires dans Qdrant."""
    try:
        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")
        import requests as _req
        vector = _pseudo_vector(query)
        body = {"vector": vector, "limit": top_k, "with_payload": True}
        resp = _req.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            json=body, timeout=5
        )
        if resp.status_code == 200:
            results = resp.json().get("result", [])
            output = f"found={len(results)}\n" + "\n".join(
                str(r.get("payload", {}))[:200] for r in results
            )
            return _ok(output, logs=[f"search top_k={top_k} → {len(results)} results"])
        return _err(f"qdrant_search_error: status={resp.status_code}")
    except Exception as e:
        return _err(f"qdrant_unavailable: {e}")


# ── TTL / Cleanup / Dedup / Summary (V3) ──────────────────────────────────────

MEMORY_TTL = {
    "short_term": 3,    # jours
    "mid_term":   30,
    "long_term":  365,
}


def memory_store_with_ttl(content: str, tags: list, memory_type: str = "mid_term") -> dict:
    """
    Stocke une entrée avec metadata expires_at (TTL automatique).

    Args:
        content: Contenu à stocker
        tags: Liste de tags
        memory_type: "short_term" (3j) / "mid_term" (30j) / "long_term" (365j)

    Returns:
        {status, output, point_id}
    """
    try:
        if memory_type not in MEMORY_TTL:
            return _err(f"invalid memory_type: {memory_type}. Use: {list(MEMORY_TTL.keys())}")
        if not content:
            return _err("content is required")

        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")

        import datetime
        ttl_days = MEMORY_TTL[memory_type]
        expires_at = (
            datetime.datetime.utcnow() + datetime.timedelta(days=ttl_days)
        ).timestamp()

        vector = _pseudo_vector(content)
        point_id = abs(hash(content + str(time.time()))) % (2 ** 31)
        payload = {
            "type": "ttl_memory",
            "content": content[:500],
            "tags": tags or [],
            "memory_type": memory_type,
            "timestamp": time.time(),
            "expires_at": expires_at,
        }
        ok = _upsert_point(point_id, vector, payload)
        if ok:
            return _ok(
                f"stored ttl_memory id={point_id} expires_in={ttl_days}d",
                logs=[f"upsert id={point_id} memory_type={memory_type}"],
                point_id=point_id,
            )
        return _err("upsert_failed")
    except Exception as e:
        return _err(f"memory_store_with_ttl failed: {e}")


def memory_cleanup_expired() -> dict:
    """
    Scroll toutes les entrées Qdrant et supprime celles avec expires_at < now.

    Returns:
        {status, deleted_count, errors}
    """
    try:
        import requests as _req

        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")

        now = time.time()
        deleted_count = 0
        errors = []
        offset = None
        logs = []

        while True:
            body = {"limit": 100, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset

            resp = _req.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                json=body, timeout=10,
            )
            if resp.status_code != 200:
                errors.append(f"scroll_error: status={resp.status_code}")
                break

            data = resp.json().get("result", {})
            points = data.get("points", [])
            next_offset = data.get("next_page_offset")

            for point in points:
                payload = point.get("payload", {})
                expires_at = payload.get("expires_at")
                if expires_at and float(expires_at) < now:
                    point_id = point.get("id")
                    del_resp = _req.post(
                        f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
                        json={"points": [point_id]},
                        timeout=5,
                    )
                    if del_resp.status_code in (200, 201):
                        deleted_count += 1
                    else:
                        errors.append(f"delete_failed id={point_id}")

            if not next_offset or not points:
                break
            offset = next_offset

        logs.append(f"cleanup done: deleted={deleted_count} errors={len(errors)}")
        return _ok(
            f"cleanup done: deleted={deleted_count}",
            logs=logs,
            deleted_count=deleted_count,
            errors=errors,
        )
    except Exception as e:
        return _err(f"memory_cleanup_expired failed: {e}")


def memory_deduplicate(collection: str = "jarvis_solutions") -> dict:
    """
    Scroll les entrées, groupe par hash(content[:100]), garde le plus récent.

    Args:
        collection: Nom de la collection Qdrant

    Returns:
        {status, duplicates_removed}
    """
    try:
        import requests as _req

        # Vérifier la collection
        r = _req.get(f"{QDRANT_URL}/collections/{collection}", timeout=3)
        if r.status_code == 404:
            return _err(f"collection '{collection}' not found")
        if r.status_code != 200:
            return _err("qdrant_unavailable")

        duplicates_removed = 0
        errors = []
        seen: dict = {}  # hash → (point_id, timestamp)
        to_delete = []
        offset = None

        while True:
            body = {"limit": 100, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset

            resp = _req.post(
                f"{QDRANT_URL}/collections/{collection}/points/scroll",
                json=body, timeout=10,
            )
            if resp.status_code != 200:
                errors.append(f"scroll_error: status={resp.status_code}")
                break

            data = resp.json().get("result", {})
            points = data.get("points", [])
            next_offset = data.get("next_page_offset")

            for point in points:
                payload = point.get("payload", {})
                content = str(payload.get("content", payload.get("problem", payload.get("solution", ""))))
                content_hash = hash(content[:100])
                ts = payload.get("timestamp", 0)
                point_id = point.get("id")

                if content_hash in seen:
                    prev_id, prev_ts = seen[content_hash]
                    if ts > prev_ts:
                        # Garder le plus récent, supprimer l'ancien
                        to_delete.append(prev_id)
                        seen[content_hash] = (point_id, ts)
                    else:
                        to_delete.append(point_id)
                else:
                    seen[content_hash] = (point_id, ts)

            if not next_offset or not points:
                break
            offset = next_offset

        # Supprimer les doublons
        for point_id in to_delete:
            del_resp = _req.post(
                f"{QDRANT_URL}/collections/{collection}/points/delete",
                json={"points": [point_id]},
                timeout=5,
            )
            if del_resp.status_code in (200, 201):
                duplicates_removed += 1
            else:
                errors.append(f"delete_failed id={point_id}")

        return _ok(
            f"deduplicate done: removed={duplicates_removed}",
            logs=[f"deduplicate collection={collection} removed={duplicates_removed}"],
            duplicates_removed=duplicates_removed,
            errors=errors,
        )
    except Exception as e:
        return _err(f"memory_deduplicate failed: {e}")


def memory_summarize_recent(n: int = 10) -> dict:
    """
    Récupère les n dernières entrées, retourne liste résumée.

    Args:
        n: Nombre d'entrées à récupérer

    Returns:
        {status, entries: list, count}
    """
    try:
        import requests as _req

        if not _ensure_solutions_collection():
            return _err("qdrant_unavailable")

        body = {"limit": max(1, min(n, 100)), "with_payload": True, "with_vector": False}
        resp = _req.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
            json=body, timeout=10,
        )
        if resp.status_code != 200:
            return _err(f"scroll_error: status={resp.status_code}")

        points = resp.json().get("result", {}).get("points", [])
        # Trier par timestamp décroissant
        points.sort(key=lambda p: p.get("payload", {}).get("timestamp", 0), reverse=True)
        points = points[:n]

        entries = []
        for p in points:
            payload = p.get("payload", {})
            content = (
                payload.get("content")
                or payload.get("problem")
                or payload.get("solution")
                or payload.get("description")
                or str(payload)
            )
            entries.append({
                "id": p.get("id"),
                "type": payload.get("type", "unknown"),
                "summary": str(content)[:80],
                "timestamp": payload.get("timestamp"),
                "tags": payload.get("tags", []),
            })

        return _ok(
            f"found={len(entries)} recent entries",
            logs=[f"summarize n={n} → {len(entries)} entries"],
            entries=entries,
            count=len(entries),
        )
    except Exception as e:
        return _err(f"memory_summarize_recent failed: {e}")
