"""Tests for server.middleware (FastAPI error handler).

Covers:
- Unhandled exceptions are caught and returned as JSON 500 responses
- Successful responses pass through the middleware unchanged

Run: pytest tests/test_middleware.py
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.middleware import error_handler


def test_error_handler_returns_json_500():
    """Unhandled RuntimeError is caught by the middleware and returned as a JSON 500 with the error message."""
    app = FastAPI()
    app.middleware("http")(error_handler)

    @app.get("/boom")
    def boom():
        raise RuntimeError("synthetic failure")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json() == {"error": "synthetic failure"}


def test_error_handler_passes_through_success():
    """Successful responses are passed through the middleware without modification."""
    app = FastAPI()
    app.middleware("http")(error_handler)

    @app.get("/ok")
    def ok():
        return {"status": "ok"}

    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
