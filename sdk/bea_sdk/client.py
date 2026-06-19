"""
bea-sdk main client
"""
from typing import Any, Dict, Optional

import httpx

from bea_sdk.exceptions import ConnectionError
from bea_sdk.memory import MemoryClient
from bea_sdk.mission import MissionClient


class BeaClient:
    """
    Main client for interacting with Bea AI Agent System.

    Provides access to mission execution, memory operations, and other Bea capabilities.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_token: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Initialize the Bea client.

        Args:
            base_url: Base URL of the Bea API server
            api_token: Optional API token for authentication
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

        # HTTP client with authentication
        headers = {}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        self._http_client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
        )

        # Sub-clients
        self.mission = MissionClient(self._http_client)
        self.memory = MemoryClient(self._http_client)

    def health_check(self) -> Dict[str, Any]:
        """
        Check if the Bea API server is healthy.

        Returns:
            Health check response
        """
        try:
            response = self._http_client.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ConnectionError(f"Health check failed: {e.response.status_code}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect to Bea server: {e}")

    def close(self):
        """Close the HTTP client."""
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
