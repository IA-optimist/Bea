from __future__ import annotations


class _DummyStream:
    def __init__(self) -> None:
        self._events = []
        self._subscribers = []

    def get_events(self):
        return self._events

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def unsubscribe(self, callback):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def rewind_to(self, event_id: str) -> bool:
        return False


import pytest


@pytest.mark.xfail(reason="ws cookie auth path not implemented yet", strict=False)
def test_mission_websocket_accepts_cookie_auth(monkeypatch):
    monkeypatch.setenv("BEA_API_TOKEN", "test-static-token")
    monkeypatch.setenv("BEA_REQUIRE_AUTH", "true")

    import api.ws as ws_mod

    monkeypatch.setitem(ws_mod.ACTIVE_STREAMS, "mission-cookie", {"stream": _DummyStream()})

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ws_mod.router)

    client = TestClient(app)
    client.cookies.set("bea_token", "test-static-token")

    with client.websocket_connect("/api/v3/mission/mission-cookie/stream") as websocket:
        websocket.send_text("ping")
        payload = websocket.receive_json()
        assert payload["type"] == "pong"
