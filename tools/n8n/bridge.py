"""
JARVIS MAX — n8n Automation Bridge
Crée, met à jour, exécute et supprime des workflows n8n via l'API REST.
"""
from __future__ import annotations
import structlog

import httpx

log = structlog.get_logger()


class N8nBridge:

    def __init__(self, settings):
        self.s       = settings
        self.base    = settings.n8n_host
        self.auth    = (settings.n8n_basic_auth_user, settings.n8n_basic_auth_password)
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            auth=self.auth,
            headers=self.headers,
            timeout=30.0,
        )

    # ── Workflow CRUD ─────────────────────────────────────────

    async def list_workflows(self) -> list[dict]:
        async with self._client() as c:
            resp = await c.get("/api/v1/workflows")
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def get_workflow(self, workflow_id: str) -> dict:
        async with self._client() as c:
            resp = await c.get(f"/api/v1/workflows/{workflow_id}")
            resp.raise_for_status()
            return resp.json()

    async def create_workflow(self, name: str, nodes: list[dict],
                               connections: dict, active: bool = False) -> dict:
        payload = {
            "name":        name,
            "nodes":       nodes,
            "connections": connections,
            "settings":    {"executionOrder": "v1"},
            "active":      active,
        }
        async with self._client() as c:
            resp = await c.post("/api/v1/workflows", json=payload)
            resp.raise_for_status()
            data = resp.json()
            log.info("n8n_workflow_created", name=name, id=data.get("id"))
            return data

    async def update_workflow(self, workflow_id: str, updates: dict) -> dict:
        # Get current, merge, update
        current = await self.get_workflow(workflow_id)
        current.update(updates)
        async with self._client() as c:
            resp = await c.put(f"/api/v1/workflows/{workflow_id}", json=current)
            resp.raise_for_status()
            log.info("n8n_workflow_updated", id=workflow_id)
            return resp.json()

    async def activate_workflow(self, workflow_id: str) -> dict:
        async with self._client() as c:
            resp = await c.patch(f"/api/v1/workflows/{workflow_id}/activate")
            resp.raise_for_status()
            return resp.json()

    async def delete_workflow(self, workflow_id: str) -> bool:
        async with self._client() as c:
            resp = await c.delete(f"/api/v1/workflows/{workflow_id}")
            resp.raise_for_status()
            log.info("n8n_workflow_deleted", id=workflow_id)
            return True

    async def run_workflow(self, workflow_id: str, data: dict | None = None) -> dict:
        """Exécute un workflow via webhook (le workflow doit avoir un nœud Webhook)."""
        payload = data or {}
        async with self._client() as c:
            resp = await c.post(
                f"/api/v1/workflows/{workflow_id}/run",
                json={"workflowData": {}, "startNodes": [], "destinationNode": "", **payload},
            )
            resp.raise_for_status()
            return resp.json()

    # ── Helpers ───────────────────────────────────────────────

    async def create_simple_http_workflow(
        self,
        name: str,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
    ) -> dict:
        """Crée un workflow simple : Trigger manuel → HTTP Request."""
        nodes = [
            {
                "id": "1",
                "name": "When clicking 'Test workflow'",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "position": [240, 300],
                "parameters": {},
            },
            {
                "id": "2",
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4,
                "position": [460, 300],
                "parameters": {
                    "method": method,
                    "url": url,
                    "sendHeaders": bool(headers),
                    "headerParameters": {
                        "parameters": [
                            {"name": k, "value": v}
                            for k, v in (headers or {}).items()
                        ]
                    },
                },
            },
        ]
        connections = {"When clicking 'Test workflow'": {"main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]}}
        return await self.create_workflow(name, nodes, connections)

    def generate_workflow_from_description(self, description: str) -> dict:
        """
        Génère un JSON de workflow basique depuis une description texte.
        Pour une génération avancée, appeler un LLM avec ce template.
        """
        return {
            "name": f"Jarvis — {description[:40]}",
            "nodes": [
                {
                    "id": "1",
                    "name": "Manual Trigger",
                    "type": "n8n-nodes-base.manualTrigger",
                    "typeVersion": 1,
                    "position": [240, 300],
                    "parameters": {},
                }
            ],
            "connections": {},
            "_description": description,
            "_generated_by": "JarvisMax",
        }
