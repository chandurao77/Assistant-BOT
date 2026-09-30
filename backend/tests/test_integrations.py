"""Tests for Slack and Teams bot integration services and routes."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.slack_bot import (
    format_slack_response,
    run_rag_query,
    verify_slack_signature,
)
from app.services.teams_bot import (
    format_teams_adaptive_card,
    parse_teams_activity,
)


# ── Slack signature verification ─────────────────────────────────────────────

class TestSlackSignature:
    def test_valid_signature(self):
        signing_secret = "test-secret-12345"
        body = b'{"type":"url_verification","challenge":"abc123"}'
        timestamp = str(int(time.time()))
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        expected_sig = "v0=" + hmac.new(
            signing_secret.encode(), sig_basestring.encode(), hashlib.sha256
        ).hexdigest()

        assert verify_slack_signature(body, timestamp, expected_sig, signing_secret) is True

    def test_invalid_signature(self):
        assert verify_slack_signature(b"body", str(int(time.time())), "v0=bad", "secret") is False

    def test_expired_timestamp(self):
        old_ts = str(int(time.time()) - 600)  # 10 minutes old
        assert verify_slack_signature(b"body", old_ts, "v0=sig", "secret") is False

    def test_empty_parameters(self):
        assert verify_slack_signature(b"body", "", "v0=sig", "secret") is False
        assert verify_slack_signature(b"body", str(int(time.time())), "", "secret") is False
        assert verify_slack_signature(b"body", str(int(time.time())), "v0=sig", "") is False


# ── Slack response formatting ────────────────────────────────────────────────

class TestSlackFormatting:
    def test_format_with_sources(self):
        result = {
            "answer": "The VPN policy requires AnyConnect.",
            "sources": [
                {"title": "VPN Guide", "url": "https://wiki.example.com/vpn", "score": 0.85},
                {"title": "IT Policies", "url": "https://wiki.example.com/it", "score": 0.72},
            ],
            "conversation_id": "test-123",
        }
        blocks = format_slack_response(result)
        assert len(blocks) == 3  # answer + divider + context
        assert blocks[0]["type"] == "section"
        assert "VPN policy" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "divider"
        assert blocks[2]["type"] == "context"

    def test_format_without_sources(self):
        result = {"answer": "Hello!", "sources": [], "conversation_id": "test"}
        blocks = format_slack_response(result)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"

    def test_format_sources_disabled(self):
        result = {
            "answer": "Answer text",
            "sources": [{"title": "Page", "url": "http://x", "score": 0.9}],
            "conversation_id": "test",
        }
        blocks = format_slack_response(result, include_sources=False)
        assert len(blocks) == 1


# ── RAG query helper ─────────────────────────────────────────────────────────

class TestRunRagQuery:
    @pytest.mark.asyncio
    async def test_run_rag_query(self):
        mock_store = AsyncMock()
        mock_store.get_history.return_value = []
        mock_store.append_turn.return_value = None

        from app.models.schemas import SourceDocument

        mock_source = SourceDocument(
            page_id="p1", title="Test Page", url="http://test",
            space_key="TST", space_name="Test", score=0.85,
            text="chunk text", content="full text", excerpt="chunk text",
        )

        async def mock_stream(*args, **kwargs):
            yield ("Hello ", None)
            yield ("world!", None)
            yield ("", [mock_source])

        mock_pipeline = AsyncMock()
        mock_pipeline.prepare_query.return_value = ("test question", None)
        mock_pipeline.stream = mock_stream

        result = await run_rag_query(
            question="test question",
            pipeline=mock_pipeline,
            conversation_store=mock_store,
            user_id="user1",
        )

        assert result["answer"] == "Hello world!"
        assert len(result["sources"]) == 1
        assert result["sources"][0]["title"] == "Test Page"
        assert "conversation_id" in result
        mock_store.append_turn.assert_called_once()


# ── Teams message parsing ────────────────────────────────────────────────────

class TestTeamsActivityParsing:
    def test_parse_message_activity(self):
        activity = {
            "type": "message",
            "text": "How do I reset my password?",
            "conversation": {"id": "conv-123"},
            "from": {"id": "user-456", "name": "John"},
            "serviceUrl": "https://smba.trafficmanager.net/teams/",
            "channelId": "msteams",
            "id": "act-789",
            "recipient": {"id": "bot-111", "name": "Assistant Bot"},
        }
        parsed = parse_teams_activity(activity)
        assert parsed is not None
        assert parsed["text"] == "How do I reset my password?"
        assert parsed["conversation_id"] == "conv-123"
        assert parsed["user_id"] == "user-456"
        assert parsed["service_url"] == "https://smba.trafficmanager.net/teams/"

    def test_parse_non_message_activity(self):
        activity = {"type": "conversationUpdate", "membersAdded": []}
        assert parse_teams_activity(activity) is None

    def test_parse_empty_text(self):
        activity = {"type": "message", "text": "", "conversation": {}, "from": {}}
        assert parse_teams_activity(activity) is None

    def test_remove_bot_mention(self):
        activity = {
            "type": "message",
            "text": "<at>Assistant Bot</at> What is the VPN policy?",
            "entities": [{"type": "mention", "text": "<at>Assistant Bot</at>"}],
            "conversation": {"id": "c1"},
            "from": {"id": "u1", "name": "Alice"},
            "serviceUrl": "https://smba.trafficmanager.net/teams/",
            "channelId": "msteams",
            "id": "a1",
            "recipient": {"id": "bot1"},
        }
        parsed = parse_teams_activity(activity)
        assert parsed is not None
        assert parsed["text"] == "What is the VPN policy?"


# ── Teams adaptive card formatting ──────────────────────────────────────────

class TestTeamsAdaptiveCard:
    def test_card_with_sources(self):
        result = {
            "answer": "You need AnyConnect VPN.",
            "sources": [
                {"title": "VPN Guide", "url": "https://wiki.example.com/vpn", "score": 0.85},
            ],
        }
        card = format_teams_adaptive_card(result)
        assert card["type"] == "message"
        assert len(card["attachments"]) == 1
        content = card["attachments"][0]["content"]
        assert content["type"] == "AdaptiveCard"
        # Answer text + Sources header + 1 source = 3 body items
        assert len(content["body"]) == 3

    def test_card_without_sources(self):
        result = {"answer": "I don't know.", "sources": []}
        card = format_teams_adaptive_card(result)
        content = card["attachments"][0]["content"]
        assert len(content["body"]) == 1  # Just the answer text
