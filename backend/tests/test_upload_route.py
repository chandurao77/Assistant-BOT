"""Integration tests for POST /api/upload."""
from __future__ import annotations

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app


def _make_mock_pipeline():
    """Build a mock pipeline with embed + vector_store."""
    pipeline = MagicMock()
    pipeline.embeddings = MagicMock()
    pipeline.embeddings.embed_batch = AsyncMock(
        side_effect=lambda texts: [[0.1] * 768 for _ in texts]
    )
    pipeline.vector_store = MagicMock()
    pipeline.vector_store.upsert_chunks = AsyncMock(return_value=None)
    pipeline.vector_store.delete_page = AsyncMock(return_value=None)
    pipeline.semantic_cache = MagicMock()
    pipeline.semantic_cache.ensure_collection = AsyncMock(return_value=None)
    pipeline.stream = AsyncMock()
    pipeline.prepare_query = AsyncMock(side_effect=lambda q: (q, None))
    return pipeline


def _make_mock_store():
    store = MagicMock()
    store.get_history = AsyncMock(return_value=[])
    store.append_turn = AsyncMock(return_value=None)
    store.record_query_analytics = AsyncMock(return_value=None)
    return store


@pytest.fixture
def client():
    """TestClient with mocked pipeline and store."""
    mock_pipeline = _make_mock_pipeline()
    mock_store = _make_mock_store()

    # Override verify_api_key so upload tests work without a real API key
    from app.api.dependencies import verify_api_key
    app.dependency_overrides[verify_api_key] = lambda: None

    with patch(
        "app.services.conversation_store.ConversationStore.create",
        new=AsyncMock(return_value=mock_store),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            yield c

    app.dependency_overrides.pop(verify_api_key, None)


class TestUploadEndpoint:
    def test_upload_txt_success(self, client):
        content = b"This is a test document with enough words to create at least one chunk."
        resp = client.post(
            "/api/upload",
            files={"file": ("test.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["filename"] == "test.txt"
        assert data["chunks"] >= 1
        assert "upload_id" in data

    def test_upload_md_success(self, client):
        content = b"# Test Doc\n\nThis is a markdown file with content for processing."
        resp = client.post(
            "/api/upload",
            files={"file": ("readme.md", io.BytesIO(content), "text/markdown")},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "readme.md"

    def test_upload_with_conversation_id(self, client):
        content = b"Test document content for conversation-scoped upload."
        resp = client.post(
            "/api/upload?conversation_id=test-conv-123",
            files={"file": ("doc.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "test-conv-123"

    def test_upload_unsupported_type_rejected(self, client):
        content = b"#!/bin/bash\necho hello"
        resp = client.post(
            "/api/upload",
            files={"file": ("script.sh", io.BytesIO(content), "text/x-shellscript")},
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_upload_exe_rejected(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("malware.exe", io.BytesIO(b"\x00\x01"), "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_upload_empty_file_rejected(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_upload_too_large_rejected(self, client):
        # 11 MB file
        content = b"x" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/upload",
            files={"file": ("big.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 413

    def test_upload_calls_embed_and_upsert(self, client):
        content = b"Enough text content to be chunked and embedded into the vector store."
        resp = client.post(
            "/api/upload",
            files={"file": ("doc.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 200
        pipeline = app.state.pipeline
        pipeline.embeddings.embed_batch.assert_called_once()
        pipeline.vector_store.upsert_chunks.assert_called_once()


class TestDeleteUpload:
    def test_delete_upload(self, client):
        resp = client.delete("/api/upload/some-upload-id")
        assert resp.status_code == 200
        assert resp.json()["upload_id"] == "some-upload-id"
        app.state.pipeline.vector_store.delete_page.assert_called_once_with(
            "upload_some-upload-id"
        )
