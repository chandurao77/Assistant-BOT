"""Integration tests for POST /api/chat/stream (RAG pipeline mocked)."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import SourceDocument


def _make_source() -> SourceDocument:
    return SourceDocument(
        page_id="p1",
        title="Test Page",
        url="https://example.com/p1",
        space_key="ENG",
        space_name="Engineering",
        excerpt="Test excerpt.",
        content="Full content text.",
        score=0.85,
    )


async def _stream_with_sources(*args, **kwargs):
    """Fake RAG stream: two tokens then sources."""
    try:
        yield "Hello", None
        yield " world", None
        yield "", [_make_source()]
    except GeneratorExit:
        return


async def _stream_no_sources(*args, **kwargs):
    """Fake RAG stream: no relevant content found."""
    try:
        yield "I could not find any relevant information", None
        yield "", []
    except GeneratorExit:
        return


def _make_mock_store(history: list[dict] | None = None) -> MagicMock:
    """Build a mock ConversationStore with async methods."""
    store = MagicMock()
    store.get_history = AsyncMock(return_value=history or [])
    store.append_turn = AsyncMock(return_value=None)
    store.record_query_analytics = AsyncMock(return_value=None)
    return store


@pytest.fixture(scope="class")
def client():
    """TestClient with a mock pipeline and conversation store injected into app.state.
    Patches ConversationStore.create so the lifespan does not overwrite our mock.
    """
    mock_pipeline = MagicMock()
    mock_pipeline.stream = _stream_with_sources
    mock_pipeline.prepare_query = AsyncMock(side_effect=lambda q: (q, None))
    mock_store = _make_mock_store()

    with patch(
        "app.services.conversation_store.ConversationStore.create",
        new=AsyncMock(return_value=mock_store),
    ), patch(
        "app.services.auth.AuthService.create",
        new=AsyncMock(return_value=MagicMock()),
    ), patch(
        "app.services.entity_store.EntityStore.create",
        new=AsyncMock(return_value=MagicMock()),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            # Guarantee state after lifespan runs
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            yield c


@pytest.fixture(scope="class")
def client_no_sources():
    """TestClient whose pipeline returns no sources."""
    mock_pipeline = MagicMock()
    mock_pipeline.stream = _stream_no_sources
    mock_pipeline.prepare_query = AsyncMock(side_effect=lambda q: (q, None))
    mock_store = _make_mock_store()

    with patch(
        "app.services.conversation_store.ConversationStore.create",
        new=AsyncMock(return_value=mock_store),
    ), patch(
        "app.services.auth.AuthService.create",
        new=AsyncMock(return_value=MagicMock()),
    ), patch(
        "app.services.entity_store.EntityStore.create",
        new=AsyncMock(return_value=MagicMock()),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            yield c


class TestChatStreamEndpoint:
    def test_returns_200(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        assert resp.status_code == 200

    def test_content_type_is_sse(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_token_events_in_response(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        assert "event: token" in resp.text

    def test_sources_event_in_response(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        assert "event: sources" in resp.text

    def test_done_event_in_response(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        assert "event: done" in resp.text

    def test_sources_payload_excludes_content_field(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "What is the VPN policy?"},
        )
        for line in resp.text.splitlines():
            if line.startswith("data:") and "page_id" in line:
                data = json.loads(line[5:].strip())
                sources = data if isinstance(data, list) else [data]
                for src in sources:
                    assert "content" not in src, "content field should be excluded from SSE"
                break

    def test_empty_question_returns_422(self, client):
        resp = client.post("/api/chat/stream", json={"question": ""})
        assert resp.status_code == 422

    def test_missing_question_returns_422(self, client):
        resp = client.post("/api/chat/stream", json={})
        assert resp.status_code == 422

    def test_conversation_id_echoed_in_tokens(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "Hello", "conversation_id": "test-conv-123"},
        )
        assert "test-conv-123" in resp.text

    def test_custom_conversation_id_used(self, client):
        resp = client.post(
            "/api/chat/stream",
            json={"question": "Question", "conversation_id": "my-session"},
        )
        assert "my-session" in resp.text

    def test_conversation_history_stored(self, client):
        """After a request, append_turn should be called on the store."""
        store = app.state.conversation_store
        store.append_turn.reset_mock()
        conv_id = "hist-test-999"
        client.post(
            "/api/chat/stream",
            json={"question": "First question", "conversation_id": conv_id},
        )
        store.append_turn.assert_called_once()
        call_args = store.append_turn.call_args
        # First positional arg is conversation_id
        assert call_args.args[0] == conv_id

    def test_multi_turn_history_passed_to_pipeline(self, client):
        """Second request should receive prior history in pipeline.stream()."""
        call_kwargs: list[dict] = []

        async def _recording_stream(*args, **kwargs):
            try:
                call_kwargs.append(kwargs)
                yield "reply", None
                yield "", [_make_source()]
            except GeneratorExit:
                return

        prior_history = [
            {"role": "user", "content": "Prior question"},
            {"role": "assistant", "content": "Prior answer"},
        ]
        # Temporarily swap pipeline and store on the shared app.state
        original_pipeline = app.state.pipeline
        original_store = app.state.conversation_store
        try:
            mock_store = _make_mock_store(history=prior_history)
            mock_pipeline = MagicMock()
            mock_pipeline.stream = _recording_stream
            mock_pipeline.prepare_query = AsyncMock(side_effect=lambda q: (q, None))
            app.state.pipeline = mock_pipeline
            app.state.conversation_store = mock_store
            conv_id = "multi-turn-42"
            client.post(
                "/api/chat/stream",
                json={"question": "Follow-up question", "conversation_id": conv_id},
            )
        finally:
            app.state.pipeline = original_pipeline
            app.state.conversation_store = original_store

        assert call_kwargs, "stream() was not called"
        history = call_kwargs[0].get("history")
        assert history is not None, "history kwarg not passed to pipeline.stream"
        assert any(m["content"] == "Prior question" for m in history)
