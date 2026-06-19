"""
bea-sdk memory client
"""
from typing import Any, Dict, List, Optional

import httpx

from bea_sdk.exceptions import MemoryError


def _unwrap(response: httpx.Response) -> Any:
    """Extract data from the APIResponse envelope used by Bea v1."""
    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class MemoryClient:
    """
    Client for memory-related operations.
    """

    def __init__(self, http_client: httpx.Client):
        """
        Initialize the memory client.

        Args:
            http_client: Shared HTTP client instance
        """
        self._client = http_client

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search vector memory for relevant context.

        Args:
            query: Search query (natural language)
            top_k: Maximum number of results to return
            filters: Optional filters for memory search

        Returns:
            List of matching memory entries with scores
        """
        try:
            payload = {
                "query": query,
                "top_k": top_k,
                "filters": filters or {},
            }
            response = self._client.post("/api/v1/memory/search", json=payload)
            response.raise_for_status()
            return _unwrap(response).get("results", [])
        except httpx.HTTPStatusError as e:
            raise MemoryError(f"Memory search failed: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MemoryError(f"Failed to search memory: {e}")

    def store(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        memory_type: str = "episodic",
    ) -> Dict[str, Any]:
        """
        Store a new entry in memory.

        Args:
            text: Text content to store
            metadata: Optional metadata for the memory entry
            memory_type: Type of memory (episodic, semantic, procedural, working)

        Returns:
            Storage confirmation with memory ID
        """
        try:
            payload = {
                "text": text,
                "metadata": metadata or {},
                "memory_type": memory_type,
            }
            response = self._client.post("/api/v1/memory/store", json=payload)
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            raise MemoryError(f"Memory storage failed: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MemoryError(f"Failed to store memory: {e}")

    def get(self, memory_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific memory entry by ID.

        Args:
            memory_id: The memory entry ID

        Returns:
            Memory entry details
        """
        try:
            response = self._client.get(f"/api/v1/memory/{memory_id}")
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise MemoryError(f"Memory not found: {memory_id}")
            raise MemoryError(f"Failed to get memory: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MemoryError(f"Failed to get memory: {e}")

    def delete(self, memory_id: str) -> Dict[str, Any]:
        """
        Delete a memory entry.

        Args:
            memory_id: The memory entry ID to delete

        Returns:
            Deletion confirmation
        """
        try:
            response = self._client.delete(f"/api/v1/memory/{memory_id}")
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            raise MemoryError(f"Memory deletion failed: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MemoryError(f"Failed to delete memory: {e}")

    def list_recent(
        self,
        limit: int = 10,
        memory_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List recent memory entries.

        Args:
            limit: Maximum number of entries to return
            memory_type: Optional filter by memory type

        Returns:
            List of recent memory entries
        """
        try:
            params = {"limit": limit}
            if memory_type:
                params["memory_type"] = memory_type

            response = self._client.get("/api/v1/memory", params=params)
            response.raise_for_status()
            return _unwrap(response).get("memories", [])
        except httpx.HTTPStatusError as e:
            raise MemoryError(f"Failed to list memory: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MemoryError(f"Failed to list memory: {e}")
