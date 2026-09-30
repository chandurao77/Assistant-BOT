"""Unit tests for app.services.content_guardrail — PII/secret redaction."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.services.content_guardrail import ContentGuardrail, _REDACTED


def _make_settings(enabled: bool = True):
    s = MagicMock()
    s.content_guardrail_enabled = enabled
    return s


class TestGuardrailDisabled:
    """When content_guardrail_enabled=False, text passes through unchanged."""

    def test_enabled_property(self):
        g = ContentGuardrail(_make_settings(enabled=False))
        assert g.enabled is False

    def test_redact_returns_original_text(self):
        g = ContentGuardrail(_make_settings(enabled=False))
        result = g.redact("password=SuperSecret123")
        assert result.text == "password=SuperSecret123"
        assert result.redaction_count == 0

    def test_redact_chunks_returns_original(self):
        g = ContentGuardrail(_make_settings(enabled=False))
        chunks = [{"title": "T", "text": "api_key=abc123xyz456789012345"}]
        cleaned, count = g.redact_chunks(chunks)
        assert count == 0
        assert cleaned[0]["text"] == chunks[0]["text"]


class TestAPIKeyRedaction:
    def test_api_key_with_equals(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("The api_key=sk-abc123def456ghi789jklmno")
        assert _REDACTED in result.text
        assert "sk-abc123def456ghi789jklmno" not in result.text
        assert result.redaction_count >= 1

    def test_auth_token_with_colon(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("auth_token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        assert _REDACTED in result.text
        assert result.redaction_count >= 1

    def test_bearer_token(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("bearer = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc")
        assert _REDACTED in result.text

    def test_access_token(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact('access_token="AAAA-BBBB-CCCC-DDDD-EEEE-FFFF"')
        assert _REDACTED in result.text


class TestAWSKeyRedaction:
    def test_aws_access_key(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("Use AKIAIOSFODNN7EXAMPLE for AWS")
        assert _REDACTED in result.text
        assert "AKIAIOSFODNN7EXAMPLE" not in result.text

    def test_aws_secret_key(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        assert _REDACTED in result.text


class TestPasswordRedaction:
    def test_password_equals(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("DB_PASSWORD=MyS3cr3tP@ss!")
        assert _REDACTED in result.text
        assert "MyS3cr3tP@ss!" not in result.text

    def test_pwd_colon(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("pwd: hunter2isnotgood")
        assert _REDACTED in result.text

    def test_secret_equals(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("secret=a1b2c3d4e5f6")
        assert _REDACTED in result.text


class TestConnectionStringRedaction:
    def test_jdbc_url(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("Use jdbc:postgresql://host:5432/mydb?user=admin&password=secret")
        assert _REDACTED in result.text

    def test_mongodb_url(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("mongodb+srv://admin:password@cluster0.example.net/db")
        assert _REDACTED in result.text


class TestPrivateKeyRedaction:
    def test_rsa_private_key(self):
        g = ContentGuardrail(_make_settings())
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        result = g.redact(text)
        assert _REDACTED in result.text

    def test_generic_private_key(self):
        g = ContentGuardrail(_make_settings())
        text = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg..."
        result = g.redact(text)
        assert _REDACTED in result.text


class TestPIIRedaction:
    def test_ssn(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("Employee SSN: 123-45-6789")
        assert _REDACTED in result.text
        assert "123-45-6789" not in result.text


class TestGitHubSlackTokens:
    def test_github_pat(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("Use ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh for auth")
        assert _REDACTED in result.text

    def test_slack_bot_token(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("Slack token: xoxb-1234567890-abcdefghij")
        assert _REDACTED in result.text


class TestGenericSecretRedaction:
    def test_token_equals_long_value(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("token=abc123def456ghi789jkl012mno")
        assert _REDACTED in result.text

    def test_credential_colon(self):
        g = ContentGuardrail(_make_settings())
        result = g.redact("credential: AABBCCDDEEFF00112233445566778899")
        assert _REDACTED in result.text


class TestSafeTextPassesThrough:
    """Normal Confluence content should NOT be redacted."""

    def test_normal_text_no_redaction(self):
        g = ContentGuardrail(_make_settings())
        text = "The deployment process uses Kubernetes pods to orchestrate containers."
        result = g.redact(text)
        assert result.text == text
        assert result.redaction_count == 0

    def test_short_values_not_caught(self):
        g = ContentGuardrail(_make_settings())
        text = "Set the flag to true."
        result = g.redact(text)
        assert result.text == text
        assert result.redaction_count == 0

    def test_normal_numbers_not_caught(self):
        g = ContentGuardrail(_make_settings())
        text = "The server runs on port 8080 with 4 CPU cores."
        result = g.redact(text)
        assert result.text == text
        assert result.redaction_count == 0


class TestRedactChunks:
    def test_redacts_multiple_chunks(self):
        g = ContentGuardrail(_make_settings())
        chunks = [
            {"title": "Page 1", "text": "api_key=sk-1234567890abcdefghij"},
            {"title": "Page 2", "text": "Normal Confluence content"},
            {"title": "Page 3", "text": "password=MyS3cr3t!"},
        ]
        cleaned, total = g.redact_chunks(chunks)
        assert total >= 2
        assert "sk-1234567890abcdefghij" not in cleaned[0]["text"]
        assert cleaned[1]["text"] == "Normal Confluence content"
        assert "MyS3cr3t!" not in cleaned[2]["text"]

    def test_preserves_titles(self):
        g = ContentGuardrail(_make_settings())
        chunks = [{"title": "My Title", "text": "password=secret123"}]
        cleaned, _ = g.redact_chunks(chunks)
        assert cleaned[0]["title"] == "My Title"
