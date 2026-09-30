#!/usr/bin/env python3
"""
Assistant Bot MCP Server — exposes the Assistant Bot RAG API as MCP tools for Copilot.

Usage (stdio):
    python mcp_stdio_proxy.py

Environment variables:
    ASSISTANT_BOT_API_URL   — Backend URL (default: http://localhost:8000)
    ASSISTANT_BOT_API_KEY   — API key for X-API-Key header (optional)
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

ASSISTANT_BOT_API_URL = os.environ.get("ASSISTANT_BOT_API_URL", "http://localhost:8000")
ASSISTANT_BOT_API_KEY = os.environ.get("ASSISTANT_BOT_API_KEY", "")

# Auto-read API key from .env if not set via environment
if not ASSISTANT_BOT_API_KEY:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("API_KEY=") and not line.startswith("#"):
                    ASSISTANT_BOT_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

mcp = FastMCP("assistant-bot-search")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if ASSISTANT_BOT_API_KEY:
        h["X-API-Key"] = ASSISTANT_BOT_API_KEY
    return h


def _format_sources(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return ""
    lines = ["\n\n---\n**Sources:**"]
    for i, s in enumerate(sources, 1):
        title = s.get("title", "Untitled")
        url = s.get("url", "")
        space = s.get("space_key", "")
        score = s.get("score", 0)
        excerpt = s.get("excerpt", "")[:200]
        lines.append(f"{i}. [{title}]({url}) (space: {space}, score: {score:.2f})")
        if excerpt:
            lines.append(f"   > {excerpt}")
    return "\n".join(lines)


@mcp.tool()
async def search_confluence(query: str, space_keys: str | None = None) -> str:
    """Search the ingested documentation and get an AI-generated answer with source citations.

    Args:
        query: Natural language question (e.g. "How does our retry logic work?")
        space_keys: Optional comma-separated space keys to filter (e.g. "ENG,OPS"). Leave empty to search all.

    Returns:
        AI-generated answer based on retrieved documentation, with source citations.
    """
    payload: dict[str, Any] = {"question": query}
    if space_keys:
        payload["space_keys"] = [k.strip() for k in space_keys.split(",")]

    # Consume SSE stream to build the full answer
    answer_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    error_msg = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
        async with client.stream(
            "POST",
            f"{ASSISTANT_BOT_API_URL}/api/chat/stream",
            json=payload,
            headers=_headers(),
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                return f"Error: Assistant Bot API returned {response.status_code}: {body.decode()}"

            current_event = ""
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    current_event = ""
                    continue
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                    continue
                if line.startswith(":"):  # comment / ping
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if current_event == "token":
                    text = event.get("text", "")
                    if text:
                        answer_parts.append(text)
                elif current_event == "sources":
                    sources = event if isinstance(event, list) else event.get("sources", [])
                elif current_event == "error":
                    error_msg = event.get("message", str(event))

    if error_msg:
        return f"Error from Assistant Bot: {error_msg}"
    if not answer_parts:
        return "No answer received from Assistant Bot. Make sure documents are ingested and the backend is running."

    answer = "".join(answer_parts)
    return answer + _format_sources(sources)


@mcp.tool()
async def list_spaces() -> str:
    """List all Confluence spaces that have been ingested into Assistant Bot.

    Returns:
        List of space keys with document counts.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{ASSISTANT_BOT_API_URL}/api/health/spaces", headers=_headers())
        if resp.status_code != 200:
            return f"Error: {resp.status_code} — {resp.text}"
        data = resp.json()
        if isinstance(data, list):
            if not data:
                return "No spaces ingested yet. Run ingestion first."
            return "Ingested spaces:\n" + "\n".join(f"• {s}" for s in data)
        return json.dumps(data, indent=2)


@mcp.tool()
async def check_health() -> str:
    """Check the health status of Assistant Bot components (backend, Qdrant, Ollama).

    Returns:
        Health status of each component and whether ingestion is running.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{ASSISTANT_BOT_API_URL}/api/health", headers=_headers())
        if resp.status_code != 200:
            return f"Error: Assistant Bot health check failed ({resp.status_code})"
        data = resp.json()
        lines = ["Assistant Bot Health Status:"]
        for key, val in data.items():
            lines.append(f"  {key}: {val}")
        return "\n".join(lines)


@mcp.tool()
async def ingest_status() -> str:
    """Check the current ingestion status — whether ingestion is running and how many documents are indexed.

    Returns:
        Ingestion status including running state and document count.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{ASSISTANT_BOT_API_URL}/api/ingest/status", headers=_headers())
        if resp.status_code != 200:
            return f"Error: {resp.status_code} — {resp.text}"
        data = resp.json()
        return json.dumps(data, indent=2)


@mcp.tool()
async def trigger_ingest(space_keys: str | None = None, full_refresh: bool = False) -> str:
    """Tell Assistant Bot to fetch and index Confluence pages using its own configured credentials.

    This starts a background ingestion job on the Assistant Bot backend.  Use ``ingest_status``
    to track progress.

    Args:
        space_keys: Comma-separated Confluence space keys to ingest (e.g. "ENG,OPS").
                    Leave empty to use Assistant Bot's default configured spaces.
        full_refresh: If True, drop existing chunks for the target spaces and re-index
                      everything from scratch.  Default is incremental (only changed pages).

    Returns:
        Confirmation that ingestion started, or an error/conflict message.
    """
    payload: dict[str, Any] = {"full_refresh": full_refresh}
    if space_keys:
        payload["space_keys"] = [k.strip() for k in space_keys.split(",")]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{ASSISTANT_BOT_API_URL}/api/ingest",
            json=payload,
            headers=_headers(),
        )
        if resp.status_code == 409:
            return "Ingestion already running. Use ingest_status to track progress."
        if resp.status_code not in (200, 202):
            return f"Error: Assistant Bot returned {resp.status_code}: {resp.text[:400]}"
        spaces_label = f" for spaces: {space_keys}" if space_keys else " (all configured spaces)"
        return (
            f"Ingestion started{spaces_label}. "
            "Use ingest_status to monitor progress."
        )


@mcp.tool()
async def push_page(
    page_id: str,
    title: str,
    space_key: str,
    html_content: str,
    url: str = "",
    last_updated: str = "",
    labels: str = "",
    space_name: str = "",
) -> str:
    """Push a single pre-fetched Confluence page into Assistant Bot for immediate indexing.

    Use this after fetching a page from Confluence with another tool or script.
    Pass the page's HTML body (``body.storage.value`` from ``get_page``) and metadata.
    Assistant Bot will chunk, embed, and index the page synchronously — no background job.

    Typical workflow::

        1. Fetch the page from Confluence (page_id="12345") with your own tool
        2. Call push_page(page_id="12345", title=..., space_key=..., html_content=body.storage.value)
        3. The page is immediately searchable via search_confluence

    Args:
        page_id:      Confluence page ID (numeric string from the get_page response).
        title:        Page title.
        space_key:    Confluence space key (e.g. 'ENG').
        html_content: HTML body — use body.storage.value from the get_page response.
        url:          Full URL to the page (for source citations in answers).
        last_updated: ISO-8601 last modified datetime (e.g. '2024-06-01T12:00:00Z').
        labels:       Comma-separated page labels/tags (optional).
        space_name:   Human-readable space name (optional, used in source display).

    Returns:
        Number of chunks indexed and any errors.
    """
    payload: dict[str, Any] = {
        "pages": [
            {
                "page_id": page_id,
                "title": title,
                "space_key": space_key,
                "space_name": space_name,
                "html_content": html_content,
                "url": url,
                "last_updated": last_updated,
                "labels": [lbl.strip() for lbl in labels.split(",") if lbl.strip()],
                "ancestor_titles": [],
            }
        ],
        "full_refresh": False,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{ASSISTANT_BOT_API_URL}/api/ingest/push-pages",
            json=payload,
            headers=_headers(),
        )
        if resp.status_code != 200:
            return f"Error: Assistant Bot returned {resp.status_code}: {resp.text[:400]}"

        result = resp.json()
        pages_ok = result.get("pages_processed", 0)
        chunks_ok = result.get("chunks_indexed", 0)
        errs = result.get("errors", [])

        if pages_ok > 0:
            msg = f"Indexed '{title}' — {chunks_ok} chunks stored."
            if errs:
                msg += f" Warnings: {errs}"
            return msg
        return f"Page not indexed (empty content or parse error). Errors: {errs}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
