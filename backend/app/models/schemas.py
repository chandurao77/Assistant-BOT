"""Pydantic v2 request / response schemas."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="User's natural language question")
    conversation_id: str | None = Field(default=None, description="Optional session ID for multi-turn")
    space_keys: list[str] | None = Field(default=None, description="Filter search to these Confluence space keys")
    # Per-request feature flags
    force_fresh: bool = Field(default=False, description="Skip semantic cache — force full pipeline execution")
    skip_rewrite: bool = Field(default=False, description="Disable query rewriter for this request")


class SourceDocument(BaseModel):
    page_id: str
    title: str
    url: str
    space_key: str
    space_name: str
    excerpt: str = Field(description="Short excerpt shown in the UI (first 500 chars)")
    content: str = Field(default="", description="Full chunk text passed to the LLM for answering")
    score: float = Field(ge=0.0, description="Relevance score (cosine similarity, BM25, or RRF-fused)")
    last_modified: str | None = Field(default=None, description="ISO-8601 date when the source was last updated")
    # Enriched metadata stored at ingest time (empty string = not yet ingested with new pipeline)
    page_type: str = Field(default="", description="howto / reference / report / general")
    labels: list[str] = Field(default_factory=list, description="Confluence page labels")
    ancestor_titles: list[str] = Field(default_factory=list, description="Page breadcrumb hierarchy")
    # OKF semantic graph fields (empty for non-OKF chunks)
    related_concepts: list[str] = Field(default_factory=list, description="OKF [[ConceptName]] semantic links")


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceDocument]
    conversation_id: str
    model: str


class StreamChunk(BaseModel):
    type: Literal["token", "sources", "error", "done"]
    content: str | list[SourceDocument] | None = None


class IngestRequest(BaseModel):
    space_keys: list[str] | None = Field(
        default=None, description="Override configured space keys for this run"
    )
    full_refresh: bool = Field(default=False, description="Drop and re-index all documents")
    fill_gaps: bool = Field(
        default=False,
        description=(
            "Find and ingest only pages that exist in Confluence but are missing from "
            "the local page index. Useful after a token rotation where some pages were "
            "previously inaccessible. Mutually exclusive with full_refresh."
        ),
    )


class JiraIngestRequest(BaseModel):
    project_keys: list[str] | None = Field(
        default=None, description="Override configured Jira project keys for this run"
    )
    full_refresh: bool = Field(default=False, description="Drop and re-index all Jira documents")


class GitHubIngestRequest(BaseModel):
    repos: list[str] | None = Field(
        default=None, description="Override configured GitHub repos for this run"
    )
    include_prs: bool = Field(default=True, description="Also ingest recent PRs")
    full_refresh: bool = Field(default=False, description="Drop and re-index all GitHub documents")


class PushPagePayload(BaseModel):
    """A single Confluence page pre-fetched from the IDE MCP or any external source."""
    page_id: str = Field(description="Confluence page ID (numeric string)")
    title: str = Field(description="Page title")
    space_key: str = Field(description="Confluence space key, e.g. 'ENG'")
    space_name: str = Field(default="", description="Human-readable space name")
    html_content: str = Field(description="Raw HTML / Confluence storage-format body")
    url: str = Field(default="", description="Full URL to the page for source citations")
    last_updated: str = Field(default="", description="ISO-8601 last modified datetime")
    labels: list[str] = Field(default_factory=list, description="Confluence page labels/tags")
    ancestor_titles: list[str] = Field(default_factory=list, description="Breadcrumb hierarchy (parent titles)")


class PushPagesRequest(BaseModel):
    """Request body for POST /api/ingest/push-pages — IDE MCP bridge endpoint.

    Accepts pre-fetched Confluence page data and runs the full ingest pipeline
    (HTML parse → chunk → embed → Qdrant upsert) without Assistant Bot calling Confluence.
    """
    pages: list[PushPagePayload] = Field(description="Pages to embed and index (recommended ≤50 per request)")
    full_refresh: bool = Field(
        default=False,
        description="Delete existing Qdrant chunks for each page before upserting"
    )
    use_okf: bool = Field(
        default=False,
        description=(
            "Convert each page to OKF structured Markdown before chunking. "
            "Uses the local LLM via Ollama. Slower but produces "
            "better structured chunks and semantic graph links."
        ),
    )


class IngestResponse(BaseModel):
    status: str
    pages_processed: int
    chunks_indexed: int
    errors: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    components: dict[str, str]
    database_type: str = "sqlite"
    ingest_running: bool = False
