"""Confluence Cloud REST API v2 client for page ingestion."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import Settings
from app.models.document import ConfluencePage

logger = logging.getLogger(__name__)

# Circuit breaker: open after 5 consecutive failures, auto-reset after 120s
_confluence_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=120,
    name="confluence",
)

_PAGE_FIELDS = (
    "id,title,body.storage,space,version,history.lastUpdated,ancestors,metadata.labels"
)


class ConfluenceClient:
    """Async Confluence Cloud client with pagination and retry logic."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.confluence_base_url.rstrip("/")
        self._auth_type = settings.confluence_auth_type
        self._auth = (settings.confluence_email, settings.confluence_api_token)
        self._token = settings.confluence_api_token
        self._page_limit = settings.confluence_page_limit
        self._space_keys = settings.confluence_space_keys
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ConfluenceClient":
        headers = {"Accept": "application/json"}
        auth = None

        if self._auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self._token}"
            logger.info("Confluence auth: Bearer token (PAT/service-account)")
        else:
            auth = self._auth
            logger.info("Confluence auth: Basic (email + API token)")

        self._client = httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=httpx.Timeout(30.0, read=60.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> dict:
        assert self._client, "Client not initialised — use async context manager"
        if _confluence_breaker.current_state == "open":
            raise pybreaker.CircuitBreakerError("Confluence circuit breaker is open — service unavailable")
        try:
            resp = await self._client.get(f"{self._base_url}{path}", params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("Rate limited by Confluence, waiting %ds", retry_after)
                await asyncio.sleep(retry_after)
                resp = await self._client.get(f"{self._base_url}{path}", params=params)
            resp.raise_for_status()
            _confluence_breaker.state.on_success()
            return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            _confluence_breaker.state.on_failure(exc)
            raise

    async def iter_pages(
        self, space_keys: list[str] | None = None
    ) -> AsyncIterator[ConfluencePage]:
        """Yield all pages across configured (or specified) spaces."""
        keys = space_keys or self._space_keys
        for space_key in keys:
            async for page in self._iter_space_pages(space_key):
                yield page

    async def iter_pages_changed_since(
        self,
        since: datetime,
        space_keys: list[str] | None = None,
    ) -> AsyncIterator[ConfluencePage]:
        """Yield only pages modified after *since* using CQL server-side filtering.

        This is much more efficient than iter_pages() for incremental ingestion
        because the Confluence server only returns pages that actually changed,
        avoiding the need to download all pages and compare client-side.
        """
        keys = space_keys or self._space_keys
        # CQL expects: yyyy-MM-dd HH:mm  (no seconds, no timezone)
        cql_date = since.strftime("%Y-%m-%d %H:%M")
        for space_key in keys:
            cql = f'space="{space_key}" AND type="page" AND lastModified > "{cql_date}"'
            logger.info("CQL incremental query: %s", cql)
            async for page in self._iter_cql_pages(cql):
                yield page

    async def _iter_cql_pages(self, cql: str) -> AsyncIterator[ConfluencePage]:
        """Paginate through CQL search results with full page content."""
        start = 0
        limit = min(50, self._page_limit)
        total_fetched = 0

        while True:
            params = {
                "cql": cql,
                "expand": _PAGE_FIELDS,
                "start": start,
                "limit": limit,
            }
            data = await self._get("/rest/api/content/search", params=params)
            results = data.get("results", [])

            if not results:
                break

            for raw in results:
                page = self._parse_page(raw)
                if page:
                    yield page
                    total_fetched += 1
                    if total_fetched >= self._page_limit:
                        return

            # Check for more pages
            total_size = data.get("totalSize", 0)
            start += limit
            if start >= total_size:
                break

    async def get_changed_page_count(
        self,
        since: datetime,
        space_keys: list[str] | None = None,
    ) -> int:
        """Return count of pages modified after *since* (lightweight CQL query)."""
        keys = space_keys or self._space_keys
        cql_date = since.strftime("%Y-%m-%d %H:%M")
        total = 0
        for space_key in keys:
            cql = f'space="{space_key}" AND type="page" AND lastModified > "{cql_date}"'
            try:
                data = await self._get("/rest/api/content/search", params={
                    "cql": cql,
                    "limit": 0,
                })
                total += data.get("totalSize", data.get("size", 0))
            except Exception:
                pass
        return total

    async def _iter_space_pages(self, space_key: str) -> AsyncIterator[ConfluencePage]:
        start = 0
        limit = min(50, self._page_limit)  # Confluence API max per request is 50
        total_fetched = 0

        while True:
            params = {
                "spaceKey": space_key,
                "type": "page",
                "status": "current",
                "expand": _PAGE_FIELDS,
                "start": start,
                "limit": limit,
            }
            data = await self._get("/rest/api/content", params=params)
            results = data.get("results", [])

            if not results:
                break

            for raw in results:
                page = self._parse_page(raw)
                if page:
                    yield page
                    total_fetched += 1
                    if total_fetched >= self._page_limit:
                        return

            links = data.get("_links", {})
            if not links.get("next"):
                break
            start += limit

    def _parse_page(self, raw: dict) -> ConfluencePage | None:
        try:
            body_html = (raw.get("body") or {}).get("storage") or {}
            body_html = body_html.get("value", "") if isinstance(body_html, dict) else ""
            if not body_html.strip():
                return None

            space = raw.get("space") or {}
            history = (raw.get("history") or {}).get("lastUpdated") or {}
            last_mod_str = history.get("when", "1970-01-01T00:00:00.000Z")
            last_modified = datetime.fromisoformat(last_mod_str.replace("Z", "+00:00"))

            labels = [
                lbl["name"]
                for lbl in (raw.get("metadata") or {})
                .get("labels", {})
                .get("results", [])
            ]
            ancestors = [a.get("title", "") for a in (raw.get("ancestors") or [])]

            base = self._base_url
            # Prefer webui link from API (works for both Server and Cloud)
            webui = (raw.get("_links") or {}).get("webui", "")
            if webui:
                page_url = f"{base}{webui}"
            else:
                page_url = f"{base}/display/{space.get('key', '')}/{raw['id']}"

            return ConfluencePage(
                page_id=raw["id"],
                title=raw.get("title", "Untitled"),
                body_html=body_html,
                space_key=space.get("key", ""),
                space_name=space.get("name", ""),
                url=page_url,
                last_modified=last_modified,
                version=(raw.get("version") or {}).get("number", 1),
                labels=labels,
                ancestor_titles=ancestors,
            )
        except Exception as exc:
            logger.warning("Failed to parse page %s: %s", raw.get("id"), exc)
            return None

    async def get_spaces(self) -> list[dict]:
        data = await self._get("/rest/api/space", params={"type": "global", "limit": 250})
        return data.get("results", [])

    async def get_page_count(self, space_keys: list[str] | None = None) -> int:
        """Return estimated total page count across specified spaces (lightweight API call)."""
        keys = space_keys or self._space_keys
        total = 0
        for space_key in keys:
            try:
                data = await self._get("/rest/api/content", params={
                    "spaceKey": space_key,
                    "type": "page",
                    "status": "current",
                    "limit": 0,
                })
                # Confluence API returns totalSize even with limit=0
                total += min(data.get("totalSize", data.get("size", 0)), self._page_limit)
            except Exception:
                pass  # Space may not exist or be inaccessible
        return total

    async def get_all_page_ids(self, space_keys: list[str] | None = None) -> set[str]:
        """Return the set of all current page IDs across the given spaces.

        Uses lightweight requests — only fetches page ID and space, no body/labels/ancestors.
        Used by fill_gaps mode to diff against the local page_index.
        """
        keys = space_keys or self._space_keys
        all_ids: set[str] = set()
        for space_key in keys:
            start = 0
            limit = 50
            while True:
                data = await self._get("/rest/api/content", params={
                    "spaceKey": space_key,
                    "type": "page",
                    "status": "current",
                    "expand": "version",  # minimal expand — just enough to confirm existence
                    "start": start,
                    "limit": limit,
                })
                results = data.get("results", [])
                if not results:
                    break
                for raw in results:
                    pid = raw.get("id")
                    if pid:
                        all_ids.add(pid)
                if not data.get("_links", {}).get("next"):
                    break
                start += limit
        return all_ids

    async def iter_pages_by_ids(self, page_ids: list[str]) -> AsyncIterator[ConfluencePage]:
        """Fetch and yield full page content for specific page IDs.

        Used by fill_gaps mode to ingest only the pages missing from page_index.
        """
        for page_id in page_ids:
            try:
                raw = await self._get(
                    f"/rest/api/content/{page_id}",
                    params={"expand": _PAGE_FIELDS},
                )
                page = self._parse_page(raw)
                if page:
                    yield page
            except Exception as exc:
                logger.warning("fill_gaps: failed to fetch page %s: %s", page_id, exc)
