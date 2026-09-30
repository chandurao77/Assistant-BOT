"""Tests for PII scrubber, per-user rate limiting, and per-request feature flags."""
from __future__ import annotations

import pytest

from app.pii_scrubber import scrub_pii, _scrub_value


# ── PII Scrubber ──────────────────────────────────────────────────────────────


class TestScrubValue:
    """Unit tests for the _scrub_value helper."""

    def test_email_masked(self):
        result = _scrub_value("Contact john.doe@example.com for help")
        assert "john.doe@example.com" not in result
        assert "***@***" in result

    def test_mac_address_masked(self):
        result = _scrub_value("Device MAC is AA:BB:CC:DD:EE:FF")
        assert "AA:BB:CC:DD:EE:FF" not in result
        assert "XX:XX:XX:XX:EE:FF" in result

    def test_ipv4_masked(self):
        result = _scrub_value("Server at 192.168.1.42")
        assert "192.168" not in result
        assert "***.***." in result
        assert ".1.42" in result

    def test_ssn_masked(self):
        result = _scrub_value("SSN: 123-45-6789")
        assert "123-45-6789" not in result
        assert "***-**-****" in result

    def test_bearer_token_masked(self):
        result = _scrub_value("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc")
        assert "eyJhbGci" not in result
        assert "Bearer [REDACTED]" in result

    def test_aws_key_masked(self):
        result = _scrub_value("key=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "AKIA[REDACTED]" in result

    def test_api_key_credential_masked(self):
        result = _scrub_value("api_key=sk-abcdef123456")
        assert "sk-abcdef123456" not in result
        assert "[REDACTED_CREDENTIAL]" in result

    def test_clean_text_unchanged(self):
        text = "Searching for Confluence documentation about deployment"
        result = _scrub_value(text)
        assert result == text


class TestScrubPiiProcessor:
    """Tests for the structlog processor function."""

    def test_debug_level_bypasses_scrubbing(self):
        event_dict = {
            "log_level": "debug",
            "event": "test",
            "email": "secret@example.com",
        }
        result = scrub_pii(None, None, event_dict)
        assert result["email"] == "secret@example.com"

    def test_info_level_scrubs(self):
        event_dict = {
            "log_level": "info",
            "event": "user_query",
            "detail": "User john@example.com asked a question",
        }
        result = scrub_pii(None, None, event_dict)
        assert "john@example.com" not in result["detail"]

    def test_safe_keys_not_scrubbed(self):
        event_dict = {
            "log_level": "info",
            "request_id": "abc-123-def",
            "conversation_id": "conv-456",
            "event": "test",
        }
        result = scrub_pii(None, None, event_dict)
        assert result["request_id"] == "abc-123-def"
        assert result["conversation_id"] == "conv-456"

    def test_non_string_values_ignored(self):
        event_dict = {
            "log_level": "info",
            "event": "test",
            "score": 0.85,
            "count": 42,
        }
        result = scrub_pii(None, None, event_dict)
        assert result["score"] == 0.85
        assert result["count"] == 42

    def test_short_strings_skipped(self):
        event_dict = {
            "log_level": "info",
            "event": "test",
            "tag": "ok",
        }
        result = scrub_pii(None, None, event_dict)
        assert result["tag"] == "ok"


# ── Per-User Rate Limiting ────────────────────────────────────────────────────


class TestPerUserRateLimitKey:
    """Test the rate limiter key extraction logic."""

    def test_extract_key_uses_ip_even_with_bearer_token(self):
        """Rate limiter should always use IP address (JWT identity verified in dependency layer)."""
        from app.main import _ChatRateLimitMiddleware
        from unittest.mock import MagicMock

        middleware = _ChatRateLimitMiddleware(MagicMock(), max_rpm=30)

        # Even with a valid JWT, should use IP
        import jwt
        token = jwt.encode({"sub": "user-42", "name": "Test"}, "secret", algorithm="HS256")

        scope = {
            "headers": [
                (b"authorization", f"Bearer {token}".encode("latin-1")),
            ],
            "client": ("10.0.0.1", 12345),
        }
        key = middleware._extract_rate_key(scope)
        assert key == "ip:10.0.0.1"

    def test_extract_key_falls_back_to_ip(self):
        """Without a valid JWT, rate limiter should fall back to IP."""
        from app.main import _ChatRateLimitMiddleware
        from unittest.mock import MagicMock

        middleware = _ChatRateLimitMiddleware(MagicMock(), max_rpm=30)
        scope = {
            "headers": [],
            "client": ("10.0.0.1", 12345),
        }
        key = middleware._extract_rate_key(scope)
        assert key == "ip:10.0.0.1"

    def test_extract_key_invalid_token_falls_back_to_ip(self):
        """Malformed JWT should fall back to IP without crashing."""
        from app.main import _ChatRateLimitMiddleware
        from unittest.mock import MagicMock

        middleware = _ChatRateLimitMiddleware(MagicMock(), max_rpm=30)
        scope = {
            "headers": [
                (b"authorization", b"Bearer not-a-real-jwt"),
            ],
            "client": ("10.0.0.1", 12345),
        }
        key = middleware._extract_rate_key(scope)
        assert key == "ip:10.0.0.1"


# ── Per-Request Feature Flags ─────────────────────────────────────────────────


class TestChatRequestFlags:
    """Test that per-request feature flags are accepted in the schema."""

    def test_default_flags_are_false(self):
        from app.models.schemas import ChatRequest
        req = ChatRequest(question="How do I deploy?")
        assert req.force_fresh is False
        assert req.skip_rewrite is False

    def test_force_fresh_accepted(self):
        from app.models.schemas import ChatRequest
        req = ChatRequest(question="How do I deploy?", force_fresh=True)
        assert req.force_fresh is True

    def test_skip_rewrite_accepted(self):
        from app.models.schemas import ChatRequest
        req = ChatRequest(question="How do I deploy?", skip_rewrite=True)
        assert req.skip_rewrite is True

    def test_both_flags_together(self):
        from app.models.schemas import ChatRequest
        req = ChatRequest(question="test", force_fresh=True, skip_rewrite=True)
        assert req.force_fresh is True
        assert req.skip_rewrite is True

    def test_flags_in_json_serialization(self):
        from app.models.schemas import ChatRequest
        req = ChatRequest(question="test", force_fresh=True)
        data = req.model_dump()
        assert data["force_fresh"] is True
        assert data["skip_rewrite"] is False
