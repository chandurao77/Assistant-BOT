"""Tests for feedback endpoints — stats, self-learning, negative feedback."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.api.dependencies import get_optional_user


def _mock_user():
    """Return a fake authenticated user for testing."""
    return {"id": "test-user", "name": "Test", "email": "test@test.com", "role": "user", "allowed_spaces": []}


def _make_mock_pipeline():
    pipeline = MagicMock()
    pipeline.embeddings = MagicMock()
    pipeline.embeddings.embed = AsyncMock(return_value=[0.1] * 768)
    pipeline.embeddings.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    pipeline.vector_store = MagicMock()
    pipeline.vector_store.upsert_chunks = AsyncMock()
    pipeline.vector_store.index_qa_pair = AsyncMock()
    pipeline.vector_store.remove_learned_qa = AsyncMock()
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
    store.save_feedback = AsyncMock()
    store.get_feedback_stats = AsyncMock(return_value={
        "total_ratings": 10,
        "positive": 8,
        "negative": 2,
        "satisfaction_rate": 0.8,
        "recent_7d_positive": 5,
        "recent_7d_negative": 1,
    })
    store.get_conversation_messages = AsyncMock(return_value=[
        {"id": "msg-user-1", "role": "user", "content": "What is Assistant Bot?"},
        {"id": "msg-asst-1", "role": "assistant", "content": "Assistant Bot is an AI assistant."},
    ])
    return store


@pytest.fixture
def client():
    mock_pipeline = _make_mock_pipeline()
    mock_store = _make_mock_store()

    with patch(
        "app.services.conversation_store.ConversationStore.create",
        new=AsyncMock(return_value=mock_store),
    ):
        app.dependency_overrides[get_optional_user] = _mock_user
        with TestClient(app, raise_server_exceptions=False) as c:
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            yield c
        app.dependency_overrides.pop(get_optional_user, None)


class TestFeedbackStats:
    def test_get_stats(self, client):
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_ratings"] == 10
        assert data["positive"] == 8
        assert data["negative"] == 2
        assert data["satisfaction_rate"] == 0.8
        assert "recent_7d_positive" in data
        assert "recent_7d_negative" in data


class TestFeedbackSubmit:
    def test_positive_feedback_triggers_self_learn(self, client):
        resp = client.post("/api/feedback", json={
            "message_id": "msg-asst-1",
            "conversation_id": "conv-1",
            "value": 1,
        })
        assert resp.status_code == 204
        store = app.state.conversation_store
        store.save_feedback.assert_called_once_with("msg-asst-1", "conv-1", 1, reason=None, reason_text=None)
        # Self-learn should have been called
        pipeline = app.state.pipeline
        pipeline.vector_store.index_qa_pair.assert_called_once()

    def test_negative_feedback_removes_learned_qa(self, client):
        resp = client.post("/api/feedback", json={
            "message_id": "msg-asst-1",
            "conversation_id": "conv-1",
            "value": -1,
        })
        assert resp.status_code == 204
        pipeline = app.state.pipeline
        pipeline.vector_store.remove_learned_qa.assert_called_once_with("msg-asst-1")

    def test_zero_feedback_is_noop(self, client):
        resp = client.post("/api/feedback", json={
            "message_id": "msg-asst-1",
            "conversation_id": "conv-1",
            "value": 0,
        })
        assert resp.status_code == 204
        store = app.state.conversation_store
        store.save_feedback.assert_not_called()
