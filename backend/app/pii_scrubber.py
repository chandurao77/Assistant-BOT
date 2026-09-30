"""
PII scrubber for structured logs.

Masks sensitive patterns (emails, MAC addresses, IPs, account IDs, SSNs,
API keys) in log output at INFO level and above.  DEBUG logs bypass
scrubbing so engineers can still diagnose issues locally.

Scrubs personal data and secrets from log output.
"""
from __future__ import annotations

import re

# ── Compiled patterns (zero-cost after module load) ─────────────────────────
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_API_KEY_RE = re.compile(r"(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+", re.IGNORECASE)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
_ACCOUNT_ID_RE = re.compile(r"\b\d{8,12}\b")

# Keys whose values are safe and should never be scrubbed
_SAFE_KEYS = frozenset({
    "request_id", "conversation_id", "user_id", "msg_id",
    "event", "level", "timestamp", "logger", "module",
    "status_code", "method", "path", "endpoint",
    "chunks", "pages", "score", "top_k", "duration",
    "environment", "env", "llm_model", "embed_model",
    "step", "error", "space_key",
})


def _scrub_value(value: str) -> str:
    """Apply all PII patterns to a single string value."""
    value = _EMAIL_RE.sub(lambda m: m.group()[:2] + "***@***", value)
    value = _MAC_RE.sub(lambda m: "XX:XX:XX:XX:" + m.group()[-5:], value)
    value = _IPV4_RE.sub(lambda m: _mask_ip(m.group()), value)
    value = _SSN_RE.sub("***-**-****", value)
    value = _API_KEY_RE.sub("[REDACTED_CREDENTIAL]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _AWS_KEY_RE.sub("AKIA[REDACTED]", value)
    # Account IDs: only mask if standalone (not part of a port or score)
    value = _ACCOUNT_ID_RE.sub(lambda m: "****" + m.group()[-4:] if len(m.group()) >= 9 else m.group(), value)
    return value


def _mask_ip(ip: str) -> str:
    """Mask first two octets of an IPv4 address."""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"***.***.{parts[2]}.{parts[3]}"
    return ip


def scrub_pii(_, __, event_dict: dict) -> dict:
    """
    Structlog processor that scrubs PII from log events.
    Bypasses scrubbing for DEBUG level to aid local development.
    """
    level = event_dict.get("log_level", event_dict.get("level", "info"))
    if level == "debug":
        return event_dict

    for key, value in event_dict.items():
        if key in _SAFE_KEYS:
            continue
        if isinstance(value, str) and len(value) > 3:
            event_dict[key] = _scrub_value(value)

    return event_dict
