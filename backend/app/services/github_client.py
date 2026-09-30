"""GitHub REST API client for repo content ingestion into RAG pipeline."""
from __future__ import annotations
import base64
import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import AsyncIterator

import httpx
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import Settings
from app.models.document import DocumentChunk

logger = logging.getLogger(__name__)

_github_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=120, name="github")


class GitHubClient:
    """Async GitHub API client for ingesting repo contents and PRs."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.github_token
        self._repos = settings.github_repos
        self._max_files = settings.github_max_files
        self._allowed_extensions = set(settings.github_file_extensions)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitHubClient":
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
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
    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        resp = await _github_breaker.call(self._client.get, path, params=params or {})
        resp.raise_for_status()
        return resp

    async def iter_repo_files(self, repo: str) -> AsyncIterator[dict]:
        """Yield file metadata from a repo's default branch (recursive tree)."""
        try:
            resp = await self._get(f"/repos/{repo}/git/trees/HEAD", params={"recursive": "1"})
            tree = resp.json().get("tree", [])
        except Exception as exc:
            logger.error("Failed to fetch tree for %s: %s", repo, exc)
            return

        count = 0
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            ext = PurePosixPath(path).suffix.lower()
            if ext not in self._allowed_extensions:
                continue
            yield {"repo": repo, "path": path, "sha": item.get("sha", "")}
            count += 1
            if count >= self._max_files:
                break

        logger.info("Found %d indexable files in %s", count, repo)

    async def get_file_content(self, repo: str, path: str) -> str | None:
        """Fetch and decode a single file's content."""
        try:
            resp = await self._get(f"/repos/{repo}/contents/{path}")
            data = resp.json()
            content = data.get("content", "")
            encoding = data.get("encoding", "")
            if encoding == "base64" and content:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return content
        except Exception as exc:
            logger.warning("Failed to fetch %s/%s: %s", repo, path, exc)
            return None

    async def iter_recent_prs(self, repo: str, limit: int = 50) -> AsyncIterator[dict]:
        """Yield recent merged/closed PRs with body text."""
        try:
            resp = await self._get(
                f"/repos/{repo}/pulls",
                params={"state": "all", "sort": "updated", "direction": "desc", "per_page": min(limit, 100)},
            )
            prs = resp.json()
        except Exception as exc:
            logger.error("Failed to fetch PRs for %s: %s", repo, exc)
            return

        for pr in prs[:limit]:
            yield pr

    async def get_repo_info(self, repo: str) -> dict | None:
        """Fetch repo metadata (for last push date)."""
        try:
            resp = await self._get(f"/repos/{repo}")
            return resp.json()
        except Exception:
            return None


def file_to_chunk(repo: str, path: str, content: str, repo_url: str = "") -> DocumentChunk:
    """Convert a GitHub file into a DocumentChunk."""
    page_id = f"github_{repo.replace('/', '_')}_{path.replace('/', '_')}"
    url = f"https://github.com/{repo}/blob/HEAD/{path}" if not repo_url else f"{repo_url}/blob/HEAD/{path}"

    return DocumentChunk(
        chunk_id=f"{page_id}_0",
        page_id=page_id,
        title=f"{repo}: {path}",
        space_key="__GITHUB__",
        space_name=f"GitHub: {repo}",
        url=url,
        text=f"# {path}\n\n{content}",
        chunk_index=0,
        total_chunks=1,
        last_modified=datetime.now(timezone.utc),
    )


def pr_to_chunk(repo: str, pr: dict) -> DocumentChunk | None:
    """Convert a GitHub PR into a DocumentChunk."""
    number = pr.get("number", 0)
    title = pr.get("title", "")
    body = pr.get("body", "") or ""
    state = pr.get("state", "")
    merged = pr.get("merged_at") is not None
    user = pr.get("user", {}).get("login", "")
    updated = pr.get("updated_at", "")
    labels = ", ".join(l.get("name", "") for l in pr.get("labels", []))

    if not title:
        return None

    parts = [
        f"PR #{number}: {title}",
        f"Author: {user} | State: {'merged' if merged else state}",
    ]
    if labels:
        parts.append(f"Labels: {labels}")
    if body:
        # Truncate very long PR bodies
        parts.append(f"\n{body[:3000]}")

    text = "\n".join(parts)
    page_id = f"github_pr_{repo.replace('/', '_')}_{number}"

    try:
        last_modified = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        last_modified = datetime.now(timezone.utc)

    return DocumentChunk(
        chunk_id=f"{page_id}_0",
        page_id=page_id,
        title=f"PR #{number}: {title}",
        space_key="__GITHUB__",
        space_name=f"GitHub: {repo}",
        url=pr.get("html_url", f"https://github.com/{repo}/pull/{number}"),
        text=text,
        chunk_index=0,
        total_chunks=1,
        last_modified=last_modified,
    )
