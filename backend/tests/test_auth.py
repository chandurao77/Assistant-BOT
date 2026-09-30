"""Tests for authentication — register, login, JWT, /me endpoint."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app


def _make_mock_pipeline():
    pipeline = MagicMock()
    pipeline.embeddings = MagicMock()
    pipeline.embeddings.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    pipeline.vector_store = MagicMock()
    pipeline.vector_store.upsert_chunks = AsyncMock()
    pipeline.semantic_cache = MagicMock()
    pipeline.semantic_cache.ensure_collection = AsyncMock()
    pipeline.stream = AsyncMock()
    pipeline.prepare_query = AsyncMock(side_effect=lambda q: (q, None))
    return pipeline


def _make_mock_store():
    store = MagicMock()
    store.get_history = AsyncMock(return_value=[])
    store.append_turn = AsyncMock()
    store.record_query_analytics = AsyncMock()
    return store


@pytest.fixture
def client(tmp_path):
    """TestClient with real AuthService backed by a temp SQLite DB."""
    from app.services.auth import AuthService
    from app.config import get_settings
    import asyncio

    db_path = str(tmp_path / "test.db")
    settings = get_settings()

    # Create auth service with temp DB
    auth_service = asyncio.run(AuthService.create(settings, db_path))
    mock_pipeline = _make_mock_pipeline()
    mock_store = _make_mock_store()

    with patch(
        "app.services.conversation_store.ConversationStore.create",
        new=AsyncMock(return_value=mock_store),
    ), patch(
        "app.services.auth.AuthService.create",
        new=AsyncMock(return_value=auth_service),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            app.state.auth = auth_service
            yield c


class TestRegister:
    def test_register_success(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["user"]["name"] == "Alice"
        assert data["user"]["email"] == "alice@example.com"
        assert "id" in data["user"]

    def test_register_duplicate_email(self, client):
        payload = {"name": "Bob", "email": "bob@example.com", "password": "pass1234"}
        resp1 = client.post("/api/auth/register", json=payload)
        assert resp1.status_code == 201
        resp2 = client.post("/api/auth/register", json=payload)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    def test_register_short_password(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Eve",
            "email": "eve@example.com",
            "password": "12345",
        })
        assert resp.status_code == 422  # validation error

    def test_register_invalid_email(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Eve",
            "email": "not-an-email",
            "password": "secret123",
        })
        assert resp.status_code == 422

    def test_register_empty_name(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "",
            "email": "empty@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 422


class TestLogin:
    def test_login_success(self, client):
        # Register first
        client.post("/api/auth/register", json={
            "name": "Charlie",
            "email": "charlie@example.com",
            "password": "mypassword",
        })
        # Login
        resp = client.post("/api/auth/login", json={
            "email": "charlie@example.com",
            "password": "mypassword",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == "charlie@example.com"

    def test_login_wrong_password(self, client):
        client.post("/api/auth/register", json={
            "name": "Dave",
            "email": "dave@example.com",
            "password": "correctpassword",
        })
        resp = client.post("/api/auth/login", json={
            "email": "dave@example.com",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_login_nonexistent_email(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "whatever",
        })
        assert resp.status_code == 401

    def test_login_case_insensitive_email(self, client):
        client.post("/api/auth/register", json={
            "name": "Frank",
            "email": "frank@example.com",
            "password": "secret123",
        })
        resp = client.post("/api/auth/login", json={
            "email": "FRANK@example.com",
            "password": "secret123",
        })
        assert resp.status_code == 200


class TestMe:
    def test_me_with_valid_token(self, client):
        reg = client.post("/api/auth/register", json={
            "name": "Grace",
            "email": "grace@example.com",
            "password": "secret123",
        })
        token = reg.json()["token"]
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Grace"
        assert data["email"] == "grace@example.com"

    def test_me_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer bad.token.here"})
        assert resp.status_code == 401

    def test_me_with_malformed_header(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Token abc"})
        assert resp.status_code == 401


class TestJWT:
    def test_token_round_trip(self, client):
        """Register → get token → decode → verify user info."""
        reg = client.post("/api/auth/register", json={
            "name": "Heidi",
            "email": "heidi@example.com",
            "password": "secret123",
        })
        token = reg.json()["token"]
        payload = app.state.auth.decode_token(token)
        assert payload is not None
        assert payload["email"] == "heidi@example.com"
        assert payload["name"] == "Heidi"
        assert "sub" in payload
        assert "exp" in payload

    def test_expired_token_rejected(self, client):
        """Token with past expiry should be rejected."""
        from datetime import datetime, timezone, timedelta
        import jwt as pyjwt
        from app.config import get_settings

        settings = get_settings()
        expired_payload = {
            "sub": "fake-id",
            "email": "test@example.com",
            "name": "Test",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = pyjwt.encode(
            expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
