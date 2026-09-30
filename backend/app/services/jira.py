"""Jira Cloud REST API client for issue ingestion into RAG pipeline."""
from __future__ import annotations
import logging
from base64 import b64encode
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import Settings
from app.models.document import DocumentChunk

logger = logging.getLogger(__name__)

_jira_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=120, name="jira")

_ISSUE_FIELDS = "summary,description,status,assignee,reporter,priority,labels,created,updated,issuetype,project,comment"


class JiraClient:
    """Async Jira Cloud client with pagination for issue ingestion."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.jira_base_url.rstrip("/")
        self._auth_type = settings.jira_auth_type
        self._auth = (settings.jira_email, settings.jira_api_token)
        self._token = settings.jira_api_token
        self._projects = settings.jira_projects
        self._max_issues = settings.jira_max_issues
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "JiraClient":
        headers = {"Accept": "application/json"}

        if self._auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self._token}"
            logger.info("Jira auth: Bearer token (PAT/service-account)")
        else:
            token = b64encode(f"{self._auth[0]}:{self._auth[1]}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
            logger.info("Jira auth: Basic (email + API token)")

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0, read=60.0),
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def _search_issues(self, jql: str, start_at: int = 0, max_results: int = 50) -> dict:
        """Execute a JQL search with retry logic."""
        resp = await _jira_breaker.call(
            self._client.get,
            "/rest/api/3/search",
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": _ISSUE_FIELDS,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def iter_issues(self, project_keys: list[str] | None = None) -> AsyncIterator[dict]:
        """Yield all issues from configured projects with pagination."""
        projects = project_keys or self._projects
        if not projects:
            logger.warning("No Jira projects configured — skipping")
            return

        for project_key in projects:
            jql = f'project = "{project_key}" ORDER BY updated DESC'
            start_at = 0
            fetched = 0

            while fetched < self._max_issues:
                batch_size = min(50, self._max_issues - fetched)
                try:
                    data = await self._search_issues(jql, start_at=start_at, max_results=batch_size)
                except Exception as exc:
                    logger.error("Jira search failed for %s at offset %d: %s", project_key, start_at, exc)
                    break

                issues = data.get("issues", [])
                if not issues:
                    break

                for issue in issues:
                    yield issue
                    fetched += 1
                    if fetched >= self._max_issues:
                        break

                start_at += len(issues)
                if start_at >= data.get("total", 0):
                    break

            logger.info("Fetched %d issues from Jira project %s", fetched, project_key)


def issue_to_chunks(issue: dict) -> list[DocumentChunk]:
    """Convert a Jira issue into DocumentChunks for embedding."""
    fields = issue.get("fields", {})
    key = issue.get("key", "")
    project = fields.get("project", {})
    project_key = project.get("key", "UNKNOWN")

    # Build rich text from issue fields
    summary = fields.get("summary", "")
    description = _extract_text(fields.get("description"))
    status = fields.get("status", {}).get("name", "")
    issue_type = fields.get("issuetype", {}).get("name", "")
    priority = fields.get("priority", {}).get("name", "") if fields.get("priority") else ""
    assignee = fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned"
    reporter = fields.get("reporter", {}).get("displayName", "") if fields.get("reporter") else ""
    labels = ", ".join(fields.get("labels", []))
    created = fields.get("created", "")[:10]
    updated = fields.get("updated", "")[:10]

    # Compose a single readable text block
    parts = [
        f"[{key}] {summary}",
        f"Type: {issue_type} | Status: {status} | Priority: {priority}",
        f"Assignee: {assignee} | Reporter: {reporter}",
    ]
    if labels:
        parts.append(f"Labels: {labels}")
    parts.append(f"Created: {created} | Updated: {updated}")
    if description:
        parts.append(f"\n{description}")

    # Add top comments (max 3)
    comments = fields.get("comment", {}).get("comments", [])
    for comment in comments[:3]:
        author = comment.get("author", {}).get("displayName", "")
        body = _extract_text(comment.get("body"))
        if body:
            parts.append(f"\nComment by {author}:\n{body}")

    text = "\n".join(parts)

    # Parse updated timestamp
    updated_raw = fields.get("updated", "")
    try:
        last_modified = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        last_modified = datetime.now(timezone.utc)

    page_id = f"jira_{key}"
    base_url = issue.get("self", "").split("/rest/")[0] if issue.get("self") else ""
    url = f"{base_url}/browse/{key}" if base_url else ""

    return [
        DocumentChunk(
            chunk_id=f"{page_id}_0",
            page_id=page_id,
            title=f"[{key}] {summary}",
            space_key="__JIRA__",
            space_name=f"Jira: {project_key}",
            url=url,
            text=text,
            chunk_index=0,
            total_chunks=1,
            last_modified=last_modified,
        )
    ]


def _extract_text(adf_node: dict | str | None) -> str:
    """Extract plain text from Atlassian Document Format (ADF) or plain string."""
    if not adf_node:
        return ""
    if isinstance(adf_node, str):
        return adf_node

    # ADF is a nested JSON structure — recursively extract text nodes
    texts = []

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(adf_node)
    raw = " ".join(t for t in texts if t)
    # Normalize whitespace (ADF text nodes may have trailing spaces)
    return " ".join(raw.split())
