"""
bea-sdk mission client
"""
from typing import Any, Dict, List, Optional

import httpx

from bea_sdk.exceptions import MissionError


def _unwrap(response: httpx.Response) -> Any:
    """Extract data from the APIResponse envelope used by Bea v1."""
    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class MissionClient:
    """
    Client for mission-related operations.
    """

    def __init__(self, http_client: httpx.Client):
        """
        Initialize the mission client.

        Args:
            http_client: Shared HTTP client instance
        """
        self._client = http_client

    def submit(
        self,
        goal: str,
        mission_type: str = "auto",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit a new mission to Bea.

        Args:
            goal: The mission goal or user input
            mission_type: Optional mission type hint (auto, coding, research, business, etc.)
            context: Optional additional context for the mission

        Returns:
            Mission submission response with mission_id
        """
        try:
            payload = {
                "goal": goal,
                "mission_type": mission_type,
                "context": context or {},
            }
            response = self._client.post("/api/v1/missions", json=payload)
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            raise MissionError(f"Mission submission failed: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MissionError(f"Failed to submit mission: {e}")

    def get_status(self, mission_id: str) -> Dict[str, Any]:
        """
        Get the current status of a mission.

        Args:
            mission_id: The mission ID

        Returns:
            Mission status and progress information
        """
        try:
            response = self._client.get(f"/api/v1/missions/{mission_id}")
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise MissionError(f"Mission not found: {mission_id}")
            raise MissionError(f"Failed to get mission status: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MissionError(f"Failed to get mission status: {e}")

    def list_missions(
        self,
        limit: int = 10,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List recent missions.

        Args:
            limit: Maximum number of missions to return
            status: Optional filter by status (DONE, FAILED, IN_PROGRESS, etc.)

        Returns:
            List of mission summaries
        """
        try:
            params = {"limit": limit}
            if status:
                params["status"] = status

            response = self._client.get("/api/v1/missions", params=params)
            response.raise_for_status()
            return _unwrap(response).get("missions", [])
        except httpx.HTTPStatusError as e:
            raise MissionError(f"Failed to list missions: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MissionError(f"Failed to list missions: {e}")

    def cancel(self, mission_id: str) -> Dict[str, Any]:
        """
        Cancel a running mission.

        Args:
            mission_id: The mission ID to cancel

        Returns:
            Cancellation confirmation
        """
        try:
            response = self._client.post(f"/api/v1/missions/{mission_id}/cancel")
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            raise MissionError(f"Failed to cancel mission: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MissionError(f"Failed to cancel mission: {e}")

    def get_result(self, mission_id: str) -> Dict[str, Any]:
        """
        Get the final result of a completed mission.

        Args:
            mission_id: The mission ID

        Returns:
            Mission result and output
        """
        try:
            response = self._client.get(f"/api/v1/missions/{mission_id}/result")
            response.raise_for_status()
            return _unwrap(response)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise MissionError(f"Mission not found: {mission_id}")
            raise MissionError(f"Failed to get mission result: {e.response.status_code}")
        except httpx.RequestError as e:
            raise MissionError(f"Failed to get mission result: {e}")
