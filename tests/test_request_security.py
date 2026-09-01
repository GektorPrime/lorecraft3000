import asyncio

from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from app.main import app
from app.middleware import LocalRequestGuardMiddleware


def test_loopback_host_and_vite_origin_are_allowed():
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 405


def test_non_local_host_is_rejected():
    client = TestClient(app, base_url="http://example.com")
    response = client.get("/health")
    assert response.status_code == 400


def test_unrelated_browser_origin_is_rejected():
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/health", headers={"Origin": "https://example.com"})
    assert response.status_code == 403


def test_local_non_browser_request_without_origin_is_allowed():
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post("/health")
    assert response.status_code == 405


def test_forged_loopback_host_from_remote_client_is_rejected():
    middleware = LocalRequestGuardMiddleware(app)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/health",
            "headers": [(b"host", b"127.0.0.1")],
            "client": ("203.0.113.10", 50000),
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "query_string": b"",
        }
    )

    async def allowed(_request):
        return Response(status_code=204)

    response = asyncio.run(middleware.dispatch(request, allowed))
    assert response.status_code == 403
