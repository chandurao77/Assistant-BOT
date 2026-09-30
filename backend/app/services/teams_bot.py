"""Microsoft Teams bot service — bridges Teams Bot Framework to the Assistant Bot RAG pipeline."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


# ── JWKS cache for Bot Framework token verification ─────────────────────────
_OPENID_METADATA_URLS = [
    "https://login.botframework.com/v1/.well-known/openidconfiguration",
    "https://login.microsoftonline.com/botframework.com/v2.0/.well-known/openid-configuration",
]
_VALID_ISSUERS = [
    "https://api.botframework.com",
    "https://sts.windows.net/",
    "https://login.microsoftonline.com/",
]
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0}
_JWKS_CACHE_TTL = 3600  # 1 hour


async def _get_jwks() -> list[dict]:
    """Fetch and cache the JWKS (JSON Web Key Set) from Bot Framework OpenID metadata."""
    import time as _time

    now = _time.time()
    if _jwks_cache["keys"] and (now - _jwks_cache["fetched_at"]) < _JWKS_CACHE_TTL:
        return _jwks_cache["keys"]

    all_keys: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for meta_url in _OPENID_METADATA_URLS:
            try:
                resp = await client.get(meta_url)
                if resp.status_code != 200:
                    continue
                jwks_uri = resp.json().get("jwks_uri", "")
                if not jwks_uri:
                    continue
                jwks_resp = await client.get(jwks_uri)
                if jwks_resp.status_code == 200:
                    all_keys.extend(jwks_resp.json().get("keys", []))
            except Exception as exc:
                logger.warning("Failed to fetch JWKS from %s: %s", meta_url, exc)

    if all_keys:
        _jwks_cache["keys"] = all_keys
        _jwks_cache["fetched_at"] = now
    return all_keys


async def verify_teams_token(auth_header: str, settings: Settings) -> bool:
    """
    Validate the Bearer token from Bot Framework using Microsoft's JWKS keys.

    Performs full cryptographic JWT signature verification against Microsoft's
    published public keys, plus issuer and audience claim validation.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    token = auth_header[7:]

    import jwt as pyjwt
    from jwt import PyJWK

    try:
        # Get the key ID from the token header to find the right public key
        unverified_header = pyjwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            logger.warning("Teams token: missing kid in header")
            return False

        # Fetch Microsoft's public keys
        jwks = await _get_jwks()
        if not jwks:
            logger.warning("Teams token: could not fetch JWKS keys")
            return False

        # Find the matching key
        matching_key = None
        for key_data in jwks:
            if key_data.get("kid") == kid:
                matching_key = PyJWK(key_data)
                break

        if not matching_key:
            logger.warning("Teams token: no matching key for kid=%r", kid)
            return False

        # Verify the token signature and decode claims
        payload = pyjwt.decode(
            token,
            matching_key.key,
            algorithms=["RS256"],
            audience=settings.teams_app_id or None,
            options={"verify_aud": bool(settings.teams_app_id)},
        )

        # Validate issuer against known Bot Framework issuers
        issuer = payload.get("iss", "")
        if not any(issuer.startswith(i) for i in _VALID_ISSUERS):
            logger.warning("Teams token: invalid issuer %r", issuer)
            return False

        return True
    except pyjwt.ExpiredSignatureError:
        logger.warning("Teams token: expired")
        return False
    except pyjwt.InvalidTokenError as exc:
        logger.warning("Teams token: invalid — %s", exc)
        return False
    except Exception as exc:
        logger.warning("Teams token verification failed: %s", exc)
        return False


def parse_teams_activity(body: dict) -> dict | None:
    """
    Parse a Bot Framework Activity and extract the question.

    Returns ``{"text": str, "conversation_id": str, "user_id": str, "service_url": str, ...}``
    or ``None`` if the activity is not a message we should respond to.
    """
    activity_type = body.get("type", "")
    if activity_type != "message":
        return None

    text = (body.get("text") or "").strip()
    # Remove bot @mention if present
    if body.get("entities"):
        for entity in body["entities"]:
            if entity.get("type") == "mention":
                mention_text = entity.get("text", "")
                text = text.replace(mention_text, "").strip()

    if not text:
        return None

    conversation = body.get("conversation", {})
    from_user = body.get("from", {})

    return {
        "text": text,
        "conversation_id": conversation.get("id", ""),
        "user_id": from_user.get("id", ""),
        "user_name": from_user.get("name", ""),
        "service_url": body.get("serviceUrl", ""),
        "channel_id": body.get("channelId", ""),
        "activity_id": body.get("id", ""),
        "recipient": body.get("recipient", {}),
        "from_user": from_user,
        "conversation": conversation,
    }


async def send_teams_reply(
    service_url: str,
    conversation_id: str,
    activity_id: str,
    reply_text: str,
    sources: list[dict] | None = None,
    recipient: dict | None = None,
    from_bot: dict | None = None,
    settings: Settings | None = None,
) -> bool:
    """Send a reply back to Teams via the Bot Framework REST API."""
    reply_url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities/{activity_id}"

    # Format answer with sources as an Adaptive Card
    body_parts = [reply_text[:4000]]
    if sources:
        body_parts.append("\n\n**Sources:**")
        for s in sources[:5]:
            if s.get("url"):
                body_parts.append(f"- [{s['title']}]({s['url']}) (score: {s['score']})")
            else:
                body_parts.append(f"- {s['title']} (score: {s['score']})")

    reply_body = {
        "type": "message",
        "from": from_bot or {},
        "conversation": {"id": conversation_id},
        "recipient": recipient or {},
        "text": "\n".join(body_parts),
        "textFormat": "markdown",
        "replyToId": activity_id,
    }

    # Get access token for Bot Framework
    token = await _get_bot_token(settings) if settings else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(reply_url, json=reply_body, headers=headers)
            if resp.status_code in (200, 201, 202):
                return True
            logger.warning("Teams reply failed: %d %s", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.error("Teams reply error: %s", exc)
        return False


async def _get_bot_token(settings: Settings) -> str | None:
    """Fetch an OAuth2 token from Microsoft for Bot Framework API calls."""
    if not settings.teams_app_id or not settings.teams_app_secret:
        return None

    token_url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.teams_app_id,
        "client_secret": settings.teams_app_secret,
        "scope": "https://api.botframework.com/.default",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code == 200:
                return resp.json().get("access_token")
            logger.warning("Teams token fetch failed: %d", resp.status_code)
    except Exception as exc:
        logger.error("Teams token fetch error: %s", exc)
    return None


def format_teams_adaptive_card(result: dict) -> dict:
    """Format a RAG result as a Teams Adaptive Card."""
    body_items: list[dict] = [
        {
            "type": "TextBlock",
            "text": result["answer"][:4000],
            "wrap": True,
        }
    ]

    if result.get("sources"):
        body_items.append({
            "type": "TextBlock",
            "text": "**Sources:**",
            "wrap": True,
            "separator": True,
        })
        for s in result["sources"][:5]:
            if s.get("url"):
                body_items.append({
                    "type": "TextBlock",
                    "text": f"[{s['title']}]({s['url']}) — score: {s['score']}",
                    "wrap": True,
                    "size": "Small",
                })
            else:
                body_items.append({
                    "type": "TextBlock",
                    "text": f"{s['title']} — score: {s['score']}",
                    "wrap": True,
                    "size": "Small",
                })

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body_items,
            },
        }],
    }
