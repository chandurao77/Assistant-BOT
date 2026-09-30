"""Slack & Microsoft Teams webhook routes for the Assistant Bot integrations."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import get_settings
from app.services.slack_bot import (
    format_slack_response,
    run_rag_query,
    verify_slack_signature,
)
from app.services.teams_bot import (
    format_teams_adaptive_card,
    parse_teams_activity,
    send_teams_reply,
    verify_teams_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["integrations"])


# ── Slack Events API ─────────────────────────────────────────────────────────

@router.post("/slack/events")
async def slack_events(request: Request):
    """
    Receive Slack Events API callbacks.

    Handles:
    - ``url_verification`` challenge (required for Slack app setup)
    - ``event_callback`` with ``app_mention`` or ``message`` events
    """
    settings = get_settings()
    if not settings.slack_bot_token:
        return Response(content="Slack integration not configured", status_code=503)

    body_bytes = await request.body()
    body = json.loads(body_bytes)

    # Verify Slack signature
    if settings.slack_signing_secret:
        ts = request.headers.get("X-Slack-Request-Timestamp", "")
        sig = request.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(body_bytes, ts, sig, settings.slack_signing_secret):
            logger.warning("Slack signature verification failed")
            return Response(content="Invalid signature", status_code=401)

    # Handle URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # Handle event callbacks
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type", "")

        # Only respond to app_mention and direct messages
        if event_type not in ("app_mention", "message"):
            return {"ok": True}

        # Skip bot messages to avoid infinite loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return {"ok": True}

        text = (event.get("text") or "").strip()
        # Remove bot mention from text
        if event_type == "app_mention":
            import re
            text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

        if not text:
            return {"ok": True}

        channel = event.get("channel", "")
        user = event.get("user", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")

        logger.info("Slack question from user=%s channel=%s: %r", user, channel, text[:80])

        # Run the RAG query
        pipeline = request.app.state.pipeline
        store = request.app.state.conversation_store

        try:
            result = await run_rag_query(
                question=text,
                pipeline=pipeline,
                conversation_store=store,
                user_id=f"slack:{user}",
                conversation_id=f"slack:{channel}:{thread_ts}",
            )

            # Post reply to Slack
            blocks = format_slack_response(result)
            await _post_slack_message(
                channel=channel,
                text=result["answer"][:3000],
                blocks=blocks,
                thread_ts=thread_ts,
                token=settings.slack_bot_token,
            )
        except Exception as exc:
            logger.exception("Slack RAG query failed: %s", exc)
            await _post_slack_message(
                channel=channel,
                text="Sorry, I encountered an error processing your question. Please try again.",
                blocks=None,
                thread_ts=thread_ts,
                token=settings.slack_bot_token,
            )

    return {"ok": True}


@router.post("/slack/command")
async def slack_slash_command(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Slack slash commands (e.g., ``/assistant How do I reset my password?``).

    Responds with the RAG answer in the channel.
    """
    settings = get_settings()
    if not settings.slack_bot_token:
        return Response(content="Slack integration not configured", status_code=503)

    # Verify signature
    body_bytes = await request.body()
    if settings.slack_signing_secret:
        ts = request.headers.get("X-Slack-Request-Timestamp", "")
        sig = request.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(body_bytes, ts, sig, settings.slack_signing_secret):
            return Response(content="Invalid signature", status_code=401)

    form = await request.form()
    text = str(form.get("text", "")).strip()
    channel = str(form.get("channel_id", ""))
    user = str(form.get("user_id", ""))
    response_url = str(form.get("response_url", ""))

    if not text:
        return {
            "response_type": "ephemeral",
            "text": "Usage: `/assistant <your question>`\nExample: `/assistant How do I set up VPN?`",
        }

    logger.info("Slack command from user=%s: %r", user, text[:80])

    # Acknowledge immediately (Slack requires < 3s response)
    # Then send the actual answer via response_url
    background_tasks.add_task(
        _handle_slash_command,
            text=text,
            user=user,
            channel=channel,
            response_url=response_url,
            request=request,
        )


    return {
        "response_type": "in_channel",
        "text": f"🔍 Looking up: _{text}_...",
    }


async def _handle_slash_command(
    text: str,
    user: str,
    channel: str,
    response_url: str,
    request: Request,
) -> None:
    """Background task to process slash command and post result via response_url."""
    import httpx

    pipeline = request.app.state.pipeline
    store = request.app.state.conversation_store

    try:
        result = await run_rag_query(
            question=text,
            pipeline=pipeline,
            conversation_store=store,
            user_id=f"slack:{user}",
            conversation_id=f"slack:cmd:{channel}:{user}",
        )
        blocks = format_slack_response(result)
        payload = {
            "response_type": "in_channel",
            "replace_original": True,
            "text": result["answer"][:3000],
            "blocks": blocks,
        }
    except Exception as exc:
        logger.exception("Slash command failed: %s", exc)
        payload = {
            "response_type": "ephemeral",
            "replace_original": True,
            "text": "Sorry, I encountered an error. Please try again.",
        }

    if response_url:
        # SSRF protection: only allow Slack's own webhook URLs
        if not response_url.startswith("https://hooks.slack.com/"):
            logger.warning("Blocked non-Slack response_url: %s", response_url[:80])
            return {"response_type": "ephemeral", "text": "Invalid response URL."}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(response_url, json=payload)
        except Exception as exc:
            logger.error("Failed to post slash command response: %s", exc)


async def _post_slack_message(
    channel: str,
    text: str,
    blocks: list[dict] | None,
    thread_ts: str,
    token: str,
) -> None:
    """Post a message to Slack using the Web API."""
    import httpx

    payload: dict = {
        "channel": channel,
        "text": text,
        "thread_ts": thread_ts,
    }
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Slack API error: %s", data.get("error"))
    except Exception as exc:
        logger.error("Failed to post Slack message: %s", exc)


# ── Microsoft Teams Bot Framework ────────────────────────────────────────────

@router.post("/teams/messages")
async def teams_messages(request: Request):
    """
    Receive Microsoft Teams Bot Framework activity messages.

    This is the messaging endpoint configured in the Azure Bot registration.
    Handles ``message`` activities and replies via the Bot Framework REST API.
    """
    settings = get_settings()
    if not settings.teams_app_id:
        return Response(content="Teams integration not configured", status_code=503)

    body = await request.json()
    activity_type = body.get("type", "")

    # Validate the Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not await verify_teams_token(auth_header, settings):
        logger.warning("Teams token verification failed")
        return Response(content="Unauthorized", status_code=401)

    # Handle conversationUpdate (bot added to conversation)
    if activity_type == "conversationUpdate":
        members = body.get("membersAdded", [])
        bot_id = body.get("recipient", {}).get("id", "")
        for member in members:
            if member.get("id") == bot_id:
                logger.info("Teams bot added to conversation %s", body.get("conversation", {}).get("id"))
        return Response(status_code=200)

    # Parse the message activity
    parsed = parse_teams_activity(body)
    if not parsed:
        return Response(status_code=200)

    logger.info(
        "Teams question from user=%s conversation=%s: %r",
        parsed["user_name"], parsed["conversation_id"], parsed["text"][:80],
    )

    pipeline = request.app.state.pipeline
    store = request.app.state.conversation_store

    try:
        result = await run_rag_query(
            question=parsed["text"],
            pipeline=pipeline,
            conversation_store=store,
            user_id=f"teams:{parsed['user_id']}",
            conversation_id=f"teams:{parsed['conversation_id']}",
        )

        # Send reply back to Teams
        await send_teams_reply(
            service_url=parsed["service_url"],
            conversation_id=parsed["conversation_id"],
            activity_id=parsed["activity_id"],
            reply_text=result["answer"],
            sources=result["sources"],
            recipient=parsed["from_user"],
            from_bot=parsed["recipient"],
            settings=settings,
        )
    except Exception as exc:
        logger.exception("Teams RAG query failed: %s", exc)
        await send_teams_reply(
            service_url=parsed["service_url"],
            conversation_id=parsed["conversation_id"],
            activity_id=parsed["activity_id"],
            reply_text="Sorry, I encountered an error processing your question. Please try again.",
            recipient=parsed["from_user"],
            from_bot=parsed["recipient"],
            settings=settings,
        )

    return Response(status_code=200)
