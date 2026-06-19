from __future__ import annotations


def test_v1_responses_carry_deprecation_headers() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.middleware import V1DeprecationMiddleware

    app = FastAPI()
    app.add_middleware(V1DeprecationMiddleware)

    @app.get("/api/v1/ping")
    def ping() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app)
    response = client.get("/api/v1/ping")

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "2026-10-01T00:00:00Z"
    assert "Deprecated API" in response.headers["Warning"]
