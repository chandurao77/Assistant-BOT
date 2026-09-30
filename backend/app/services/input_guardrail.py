"""
Input guardrail — detects prompt injection and jailbreak attempts
before the query enters the RAG pipeline.

Catches ~80% of common injection patterns with simple regex matching.
Runs before embedding / LLM compute to save resources on malicious queries.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Injection patterns ────────────────────────────────────────────────────────
# Each tuple: (name, compiled_regex)
# Patterns are case-insensitive and match common prompt injection phrases.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Direct instruction override
    ("ignore_instructions", re.compile(
        r"(?i)ignore\s+(all\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|rules?|prompts?|guidelines?)",
    )),
    # System prompt extraction
    ("system_prompt_extract", re.compile(
        r"(?i)(show|reveal|print|output|display|repeat|give\s+me|what\s+(is|are))\s+"
        r"(your|the)\s+(system\s+prompt|instructions?|rules?|initial\s+prompt|hidden\s+prompt)",
    )),
    # Role hijacking
    ("role_hijack", re.compile(
        r"(?i)(you\s+are\s+now|act\s+as|pretend\s+(to\s+be|you\s+are)|"
        r"from\s+now\s+on\s+you|switch\s+to|enter\s+.{0,20}\s+mode)",
    )),
    # DAN / jailbreak patterns
    ("dan_jailbreak", re.compile(
        r"(?i)(DAN|do\s+anything\s+now|jailbreak|bypass\s+(safety|filter|restriction|guardrail))",
    )),
    # Delimiter injection (trying to close/open context blocks)
    ("delimiter_injection", re.compile(
        r"</(context|system|instructions?)>|<(system|instructions?)\s*>",
    )),
    # "Forget everything" pattern
    ("forget_everything", re.compile(
        r"(?i)(forget|disregard|discard|override)\s+(everything|all|what)\s+"
        r"(you\s+know|above|before|previously|i\s+said)",
    )),
]


class InputGuardrail:
    """
    Scans user input for prompt injection and jailbreak patterns.

    Usage::
        guardrail = InputGuardrail()
        is_blocked, reason = guardrail.check("ignore all previous instructions")
        # is_blocked=True, reason="ignore_instructions"
    """

    def __init__(self) -> None:
        self._patterns = list(_INJECTION_PATTERNS)

    def check(self, text: str) -> tuple[bool, str | None]:
        """
        Check user input for injection patterns.

        Returns ``(is_blocked, pattern_name)`` — if blocked, ``pattern_name``
        identifies which rule triggered.
        """
        for name, pattern in self._patterns:
            if pattern.search(text):
                logger.warning(
                    "Input guardrail BLOCKED query — pattern=%s, input=%r",
                    name, text[:100],
                )
                return True, name
        return False, None
