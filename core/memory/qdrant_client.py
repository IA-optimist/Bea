from __future__ import annotations

import os
from typing import Any, cast

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTIONS: dict[str, dict[str, object]] = {
    "beamax_memory_384": {"size": 384, "distance": "Cosine"},
    "bea_continual_memory": {"size": 768, "distance": "Cosine"},
    "beamax_knowledge": {"size": 768, "distance": "Cosine"},
}


class QdrantWrapper:
    def __init__(self, url: str = QDRANT_URL, api_key: str = QDRANT_API_KEY) -> None:
        self.url = url.rstrip("/")
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self.headers["api-key"] = api_key
        self._session: Any = None

    def _sess(self) -> Any:
        if self._session is None:
            import httpx

            self._session = httpx.Client(headers=self.headers)
        return self._session

    def health(self) -> bool:
        try:
            r = self._sess().get(f"{self.url}/healthz", timeout=3)
            return int(r.status_code) == 200
        except Exception:
            return False

    def ensure_collection(self, collection: str, size: int = 768) -> bool:
        try:
            cfg = COLLECTIONS.get(collection, {"size": size, "distance": "Cosine"})
            r = self._sess().put(
                f"{self.url}/collections/{collection}",
                json={"vectors": {"size": cfg["size"], "distance": cfg["distance"]}},
                timeout=10,
            )
            return r.status_code in (200, 409)
        except Exception:
            return False

    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict[str, Any]) -> bool:
        try:
            _id = abs(hash(point_id)) % (2**53)
            r = self._sess().put(
                f"{self.url}/collections/{collection}/points",
                json={"points": [{"id": _id, "vector": vector, "payload": payload}]},
                timeout=15,
            )
            r.raise_for_status()
            return True
        except Exception:
            return False

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        score_threshold: float = 0.3,
        filter_dict: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            body: dict[str, Any] = {
                "vector": vector,
                "limit": limit,
                "score_threshold": score_threshold,
                "with_payload": True,
            }
            if filter_dict:
                body["filter"] = filter_dict
            r = self._sess().post(f"{self.url}/collections/{collection}/points/search", json=body, timeout=10)
            r.raise_for_status()
            return [cast(dict[str, Any], {"id": h["id"], "score": h["score"], "payload": h.get("payload", {})}) for h in r.json().get("result", [])]
        except Exception:
            return []

    def delete(self, collection: str, point_id: str) -> bool:
        try:
            _id = abs(hash(point_id)) % (2**53)
            r = self._sess().post(
                f"{self.url}/collections/{collection}/points/delete",
                json={"points": [_id]},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception:
            return False

    def count(self, collection: str) -> int:
        try:
            r = self._sess().get(f"{self.url}/collections/{collection}", timeout=5)
            return int(r.json().get("result", {}).get("points_count", 0))
        except Exception:
            return -1


_client: QdrantWrapper | None = None


def get_qdrant() -> QdrantWrapper:
    global _client
    if _client is None:
        _client = QdrantWrapper()
    return _client
