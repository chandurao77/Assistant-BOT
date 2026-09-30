"""OKF (Organized Knowledge Format) converter.

Converts raw Confluence pages to structured Markdown.

Conversion runs on a local model through Ollama streaming (``ollama_rerank_model``
if set, otherwise ``ollama_llm_model``).

Output files saved to ``okf_knowledge_base/`` and reused on subsequent runs (skip-if-exists).

Usage (programmatic within FastAPI):
    converter = OKFConverter(settings)
    result = await converter.convert_page(page)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import Settings
from app.models.document import ConfluencePage
from app.utils.html_parser import html_to_text

logger = logging.getLogger(__name__)

# ── OKF schema — used as the conversion task prompt ──────────────────────────
_OKF_QUESTION = """\
Reformat the provided documentation page into OKF (Organized Knowledge Format) \
structured Markdown. Output ONLY the Markdown starting with # [Concept Name]. \
No preamble, no code fences around the whole document.

Use EXACTLY this schema:

# [Concept Name]

## Summary
One paragraph plain-English explanation.

## Key Facts
- Fact 1 (max 10 facts)
- Fact 2

## How It Works
Step-by-step or bullet explanation of the process/feature.

## Common Issues / FAQs
**Q: Question?**
A: Answer.
(Omit this section if no troubleshooting content exists.)

## Related Concepts
- [[ConceptA]]
- [[ConceptB]]
(Extract [[links]] from any hyperlinks, "see also" sections, or mentions of other \
services/pages. Use the EXACT title inside [[ ]]. Write "None" if no concepts.)

## Metadata
- Source: {source_url}
- Space: {space_key}
- Last Updated: {last_updated}
- Status: {status}

Rules:
- Keep technical terms, acronyms, and product names exactly as written.
- Discard navigation elements, breadcrumbs, and formatting artifacts.
- Status = "deprecated" if labels contain "deprecated" OR text mentions \
"deprecated", "legacy", or "do not use". Otherwise "active".
- Write "N/A" under any heading with no relevant content. Do NOT omit headings.
"""

_OLLAMA_SYSTEM = (
    "You are a technical documentation formatter. "
    "Output ONLY structured Markdown as instructed. No preamble or explanation."
)

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0


@dataclass
class ConversionStats:
    """Token usage and timing for one page conversion."""
    page_id: str
    title: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0
    skipped: bool = False
    error: str = ""
    provider: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ConversionResult:
    """Full result of converting one page."""
    page_id: str
    title: str
    okf_markdown: str
    file_path: Path | None
    stats: ConversionStats
    success: bool

    @property
    def related_concepts(self) -> list[str]:
        """Parse [[ConceptName]] links from the Related Concepts section."""
        m = re.search(
            r"## Related Concepts\s*\n(.*?)(?=\n##|\Z)", self.okf_markdown, re.DOTALL
        )
        if not m:
            return []
        return re.findall(r"\[\[(.+?)\]\]", m.group(1))


class OKFConverter:
    """Convert Confluence pages to OKF structured Markdown.

    Uses the local Ollama /api/generate endpoint with streaming.

    Args:
        settings: Application settings.
        output_dir: Directory to save OKF files (default: /app/okf_knowledge_base).
        concurrency: Max parallel calls (default 1 — local CPU inference).
    """

    def __init__(
        self,
        settings: Settings,
        output_dir: Path | None = None,
        concurrency: int | None = None,
    ) -> None:
        self._settings = settings

        rerank_model = getattr(settings, "ollama_rerank_model", "")
        self._ollama_model = rerank_model or settings.ollama_llm_model
        self._ollama_url = settings.ollama_base_url.rstrip("/") + "/api/generate"
        read_timeout = getattr(settings, "ollama_read_timeout", 300)
        self._ollama_timeout = httpx.Timeout(connect=10, read=read_timeout, write=10, pool=10)

        # Default concurrency: 1 — local CPU inference
        if concurrency is None:
            concurrency = 1
        self._semaphore = asyncio.Semaphore(concurrency)

        self._output_dir = output_dir or Path("/app/okf_knowledge_base")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._failed_log = self._output_dir.parent / "failed_conversions.json"

        logger.info("OKFConverter ready — provider: ollama/%s | output: %s", self._ollama_model, self._output_dir)

    # ── Public API ────────────────────────────────────────────────────────────

    async def convert_page(self, page: ConfluencePage) -> ConversionResult:
        """Convert one page to OKF. Returns cached result if file exists."""
        file_path = self._output_dir / f"{page.page_id}.md"
        if file_path.exists():
            cached = file_path.read_text(encoding="utf-8")
            return ConversionResult(
                page_id=page.page_id, title=page.title,
                okf_markdown=cached, file_path=file_path,
                stats=ConversionStats(page_id=page.page_id, title=page.title, skipped=True),
                success=True,
            )
        return await self._convert_with_retry(page)

    async def convert_batch(
        self, pages: list[ConfluencePage], force_reconvert: bool = False
    ) -> list[ConversionResult]:
        """Convert pages concurrently (bounded by semaphore)."""
        if force_reconvert:
            for page in pages:
                fp = self._output_dir / f"{page.page_id}.md"
                if fp.exists():
                    fp.unlink()

        results = await asyncio.gather(
            *[self.convert_page(page) for page in pages],
            return_exceptions=True,
        )

        final: list[ConversionResult] = []
        for page, res in zip(pages, results):
            if isinstance(res, Exception):
                logger.error("OKF unexpected error for '%s': %s", page.title, res)
                final.append(ConversionResult(
                    page_id=page.page_id, title=page.title, okf_markdown="", file_path=None,
                    stats=ConversionStats(page_id=page.page_id, title=page.title, error=str(res)),
                    success=False,
                ))
            else:
                final.append(res)  # type: ignore[arg-type]

        self._write_failures(final)
        self._log_summary(final)
        return final

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _convert_with_retry(self, page: ConfluencePage) -> ConversionResult:
        body = page.body_html or ""
        plain = html_to_text(body) if "<" in body else body
        if not plain.strip():
            return ConversionResult(
                page_id=page.page_id, title=page.title, okf_markdown="", file_path=None,
                stats=ConversionStats(page_id=page.page_id, title=page.title, error="empty body"),
                success=False,
            )

        last_error = ""
        async with self._semaphore:
            for attempt in range(1, _RETRY_ATTEMPTS + 1):
                try:
                    return await self._call_ollama(page, plain)
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempt < _RETRY_ATTEMPTS:
                        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "OKF attempt %d/%d failed for '%s': %s — retry in %.1fs",
                            attempt, _RETRY_ATTEMPTS, page.title, last_error, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("OKF all %d attempts failed for '%s': %s",
                                     _RETRY_ATTEMPTS, page.title, last_error)

        return ConversionResult(
            page_id=page.page_id, title=page.title, okf_markdown="", file_path=None,
            stats=ConversionStats(page_id=page.page_id, title=page.title, error=last_error),
            success=False,
        )

    async def _call_ollama(self, page: ConfluencePage, plain_text: str) -> ConversionResult:
        """Convert using Ollama /api/generate with streaming."""
        t0 = time.monotonic()
        if len(plain_text) <= 6000:
            page_content = plain_text
        else:
            page_content = plain_text[:4000] + "\n\n[...middle truncated...]\n\n" + plain_text[-1500:]
        prompt = (
            f"{_OLLAMA_SYSTEM}\n\n"
            + _OKF_QUESTION.format(
                source_url=page.url,
                space_key=page.space_key,
                last_updated=page.last_modified.strftime("%Y-%m-%d"),
                status=self._detect_status(plain_text, page.labels),
            )
            + f"\n\nPAGE TITLE: {page.title}\nCONTENT:\n{page_content}"
        )

        full_response = ""
        prompt_tokens = completion_tokens = 0

        async with httpx.AsyncClient(timeout=self._ollama_timeout) as client:
            async with client.stream("POST", self._ollama_url, json={
                "model": self._ollama_model, "prompt": prompt,
                "stream": True, "options": {"temperature": 0.0, "num_predict": 1024},
            }) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    full_response += chunk.get("response", "")
                    if chunk.get("done"):
                        prompt_tokens = chunk.get("prompt_eval_count", 0)
                        completion_tokens = chunk.get("eval_count", 0)
                        break

        okf_md = self._clean_and_validate(full_response.strip(), page.title)
        duration = time.monotonic() - t0
        file_path = self._output_dir / f"{page.page_id}.md"
        file_path.write_text(okf_md, encoding="utf-8")

        logger.info("OKF [Ollama/%s]: '%s' in %.1fs | %dp+%dc tokens",
                    self._ollama_model, page.title, duration, prompt_tokens, completion_tokens)
        return ConversionResult(
            page_id=page.page_id, title=page.title, okf_markdown=okf_md, file_path=file_path,
            stats=ConversionStats(
                page_id=page.page_id, title=page.title,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                duration_s=round(duration, 2), provider=f"ollama/{self._ollama_model}",
            ),
            success=True,
        )

    @staticmethod
    def _detect_status(plain_text: str, labels: list[str]) -> str:
        if {"deprecated", "legacy", "archived"} & {l.lower() for l in labels}:
            return "deprecated"
        tl = plain_text.lower()
        if any(w in tl for w in ("deprecated", "do not use", "no longer supported")):
            return "deprecated"
        return "active"

    @staticmethod
    def _clean_and_validate(okf_md: str, title: str) -> str:
        if not okf_md.startswith("#"):
            for i, line in enumerate(okf_md.splitlines()):
                if line.startswith("#"):
                    okf_md = "\n".join(okf_md.splitlines()[i:])
                    break
            else:
                raise ValueError(f"No OKF heading produced for '{title}'. Got: {okf_md[:200]!r}")
        return okf_md

    def _write_failures(self, results: list[ConversionResult]) -> None:
        failures = [
            {"page_id": r.page_id, "title": r.title, "error": r.stats.error}
            for r in results if not r.success and r.stats.error
        ]
        if not failures:
            return
        existing: list[dict] = []
        if self._failed_log.exists():
            try:
                existing = json.loads(self._failed_log.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        ids = {f["page_id"] for f in existing}
        existing.extend(f for f in failures if f["page_id"] not in ids)
        self._failed_log.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _log_summary(results: list[ConversionResult]) -> None:
        ok = sum(1 for r in results if r.success and not r.stats.skipped)
        skip = sum(1 for r in results if r.stats.skipped)
        fail = sum(1 for r in results if not r.success)
        logger.info("OKF batch done: %d converted, %d skipped, %d failed", ok, skip, fail)
