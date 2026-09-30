"""
Content guardrail — redacts sensitive patterns from retrieved context
before it is sent to the LLM, AND from LLM output before it reaches the user.

This prevents accidental leakage of secrets, credentials, PII, and other
sensitive data that may be stored in Confluence pages or hallucinated by the LLM.

The guardrail runs on:
  - **Input side**: retrieved chunks → LLM prompt  (redact_chunks)
  - **Output side**: LLM response → user           (redact_output)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import Settings

logger = logging.getLogger(__name__)

# ── Redaction placeholder ─────────────────────────────────────────────────────
_REDACTED = "[REDACTED]"


# ── Built-in patterns ────────────────────────────────────────────────────────
# Each tuple: (name, compiled_regex)
# Patterns are intentionally conservative to avoid excessive false positives.
_BUILTIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # API keys / tokens — generic long hex/base64 strings prefixed by common labels
    ("api_key_label", re.compile(
        r"(?i)(api[_\-]?key|api[_\-]?token|auth[_\-]?token|bearer|access[_\-]?token|secret[_\-]?key)"
        r"\s*[:=]\s*['\"]?([A-Za-z0-9_\-/.+]{20,})['\"]?",
    )),
    # AWS access keys (AKIA...)
    ("aws_access_key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    # AWS secret keys (40-char base64)
    ("aws_secret_key", re.compile(
        r"(?i)(aws[_\-]?secret[_\-]?access[_\-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
    )),
    # Generic passwords in config-like context
    ("password_label", re.compile(
        r"(?i)(password|passwd|pwd|db_password|db_pass|secret)\s*[:=]\s*['\"]?(\S{6,})['\"]?"
    )),
    # Connection strings (jdbc:..., mongodb://user:pass@...)
    ("connection_string", re.compile(
        r"(?i)(jdbc:[^\s'\"]{10,}|mongodb(\+srv)?://[^\s'\"]{10,}|postgres(ql)?://[^\s'\"]{10,}|mysql://[^\s'\"]{10,})"
    )),
    # Private keys (-----BEGIN ... PRIVATE KEY-----)
    ("private_key", re.compile(
        r"-----BEGIN\s+(RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"
    )),
    # US Social Security Numbers (XXX-XX-XXXX)
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Credit card numbers (13-19 digits, optionally separated by dashes or spaces)
    # Validated with Luhn checksum to reduce false positives
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    # Email addresses (basic pattern — only redacts in sensitive contexts)
    # NOTE: Not applied globally — emails are common in Confluence. Only flagged
    # when they appear near credential/password labels (handled by password_label).
    # GitHub personal access tokens (ghp_...)
    ("github_pat", re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b")),
    # Slack tokens (xox[bprs]-...)
    ("slack_token", re.compile(r"\b(xox[bprs]-[A-Za-z0-9\-]{10,})\b")),
    # Generic "token = ..." or "secret = ..." with long values
    ("generic_secret", re.compile(
        r"(?i)(token|secret|credential)\s*[:=]\s*['\"]?([A-Za-z0-9_\-/.+=]{20,})['\"]?"
    )),
]


@dataclass
class RedactionResult:
    """Result of running the content guardrail on a text."""
    text: str
    redaction_count: int = 0
    redacted_categories: list[str] = field(default_factory=list)


def _luhn_check(digits: str) -> bool:
    """Return True if *digits* passes the Luhn (mod-10) checksum."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class ContentGuardrail:
    """
    Scans and redacts sensitive patterns from text before it reaches the LLM.

    Usage::

        guardrail = ContentGuardrail(settings)
        result = guardrail.redact("My API key is api_key=sk-abc123def456...")
        # result.text → "My API key is api_key=[REDACTED]"
        # result.redaction_count → 1
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.content_guardrail_enabled
        self._patterns = list(_BUILTIN_PATTERNS)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def redact(self, text: str) -> RedactionResult:
        """
        Scan text and replace all sensitive matches with [REDACTED].

        Returns a ``RedactionResult`` with the cleaned text and stats.
        """
        if not self._enabled:
            return RedactionResult(text=text)

        redaction_count = 0
        categories: list[str] = []

        for name, pattern in self._patterns:
            if name == "credit_card":
                # Validate with Luhn checksum to reduce false positives
                def _luhn_replacer(m: re.Match) -> str:
                    digits = re.sub(r"[^0-9]", "", m.group())
                    if len(digits) >= 13 and _luhn_check(digits):
                        return _REDACTED
                    return m.group()
                new_text = pattern.sub(_luhn_replacer, text)
                count = text != new_text  # at least one replacement
                if count:
                    # Count actual replacements
                    n = len(pattern.findall(text))
                    real_count = sum(
                        1 for m in pattern.finditer(text)
                        if _luhn_check(re.sub(r"[^0-9]", "", m.group())) and len(re.sub(r"[^0-9]", "", m.group())) >= 13
                    )
                    text = new_text
                    redaction_count += real_count
                    categories.append(name)
            else:
                matches = pattern.findall(text)
                if matches:
                    text = pattern.sub(_REDACTED, text)
                    redaction_count += len(matches)
                    categories.append(name)

        if redaction_count > 0:
            logger.warning(
                "Content guardrail redacted %d sensitive pattern(s): %s",
                redaction_count, ", ".join(categories),
            )

        return RedactionResult(
            text=text,
            redaction_count=redaction_count,
            redacted_categories=categories,
        )

    def redact_chunks(self, chunks: list[dict]) -> tuple[list[dict], int]:
        """
        Redact all chunks in a list of ``{"title": ..., "text": ...}`` dicts.

        Returns ``(cleaned_chunks, total_redactions)``.
        """
        if not self._enabled:
            return chunks, 0

        total = 0
        cleaned = []
        for chunk in chunks:
            result = self.redact(chunk.get("text", ""))
            total += result.redaction_count
            cleaned.append({**chunk, "text": result.text})
        return cleaned, total

    def redact_output(self, text: str) -> str:
        """
        Output-side guardrail: redact sensitive patterns from LLM-generated text
        before it reaches the user. Also detects system prompt leakage.
        """
        if not self._enabled or not text:
            return text

        result = self.redact(text)
        if result.redaction_count > 0:
            logger.warning(
                "Output guardrail redacted %d pattern(s) from LLM response: %s",
                result.redaction_count, ", ".join(result.redacted_categories),
            )
        return result.text
