"""Intent router — determines which data sources to query for a given question.

Classifies questions into Confluence, Jira, GitHub, or all sources
using keyword heuristics. Fast, no LLM call required.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# Source type constants
SOURCE_CONFLUENCE = "confluence"
SOURCE_JIRA = "jira"
SOURCE_GITHUB = "github"
ALL_SOURCES = [SOURCE_CONFLUENCE, SOURCE_JIRA, SOURCE_GITHUB]

# Keyword patterns for each source
_JIRA_PATTERNS = [
    r"\bjira\b",
    r"\bticket[s]?\b",
    r"\bissue[s]?\b",
    r"\bepic[s]?\b",
    r"\bsprint[s]?\b",
    r"\bstory\b",
    r"\bstories\b",
    r"\bkanban\b",
    r"\bbacklog\b",
    r"\buser\s+stor",
    r"\bbug[s]?\b",
    r"\bdefect[s]?\b",
    r"\bassigned\s+to\b",
    r"\bstatus\b.*\b(open|closed|done|in\s*progress|todo|blocked)\b",
    r"[A-Z]{2,10}-\d+",  # e.g. MESH-123, ENG-456
]

_GITHUB_PATTERNS = [
    r"\bgithub\b",
    r"\bpull\s+request[s]?\b",
    r"\bPR[s]?\b",
    r"\bmerge[d]?\b",
    r"\bbranch\b",
    r"\bcommit[s]?\b",
    r"\brepository\b",
    r"\brepo[s]?\b",
    r"\bsource\s*code\b",
    r"\bcode\s+review\b",
    r"\breadme\b",
    r"\bworkflow[s]?\b",
    r"\bci[\s/]cd\b",
    r"\bgit\b",
]

_CONFLUENCE_PATTERNS = [
    r"\bconfluence\b",
    r"\bwiki\b",
    r"\bdocumentation\b",
    r"\bdocs?\b",
    r"\bpage[s]?\b",
    r"\bspace[s]?\b",
    r"\brunbook[s]?\b",
    r"\bplaybook[s]?\b",
    r"\bonboarding\b",
    r"\barchitecture\b",
    r"\bdesign\s+doc\b",
    r"\bknowledge\s+base\b",
]


@dataclass
class IntentResult:
    """Result of intent classification."""
    sources: list[str]
    confidence: float  # 0.0-1.0
    matched_source: str | None  # Primary matched source, None = all

    @property
    def space_key_filters(self) -> list[str] | None:
        """Convert sources to space_key filters for VectorStore.search().

        Returns None (no filter) if all sources should be queried.
        """
        if set(self.sources) == set(ALL_SOURCES):
            return None  # No filter — search everything
        filters = []
        if SOURCE_JIRA in self.sources:
            filters.append("__JIRA__")
        if SOURCE_GITHUB in self.sources:
            filters.append("__GITHUB__")
        if SOURCE_CONFLUENCE in self.sources:
            # Don't add a filter for Confluence — it uses dynamic space keys
            # Instead return None to search all (Confluence is the default)
            return None
        return filters if filters else None


def classify_intent(question: str) -> IntentResult:
    """Classify a question to determine which data sources to search.

    Returns an IntentResult with the list of sources and confidence.
    """
    q = question.lower()

    jira_score = sum(1 for p in _JIRA_PATTERNS if re.search(p, q, re.IGNORECASE))
    github_score = sum(1 for p in _GITHUB_PATTERNS if re.search(p, q, re.IGNORECASE))
    confluence_score = sum(1 for p in _CONFLUENCE_PATTERNS if re.search(p, q, re.IGNORECASE))

    # Jira ticket reference (e.g. MESH-123) is a strong signal — boost score
    if re.search(r"[A-Z]{2,10}-\d+", question):  # case-sensitive on original
        jira_score += 2

    total = jira_score + github_score + confluence_score

    # No clear signal → search all sources
    if total == 0:
        return IntentResult(sources=ALL_SOURCES, confidence=0.3, matched_source=None)

    # Strong Jira signal
    if jira_score >= 2 and jira_score > github_score and jira_score > confluence_score:
        return IntentResult(sources=[SOURCE_JIRA, SOURCE_CONFLUENCE], confidence=min(0.9, 0.5 + jira_score * 0.1), matched_source=SOURCE_JIRA)

    # Strong GitHub signal
    if github_score >= 2 and github_score > jira_score and github_score > confluence_score:
        return IntentResult(sources=[SOURCE_GITHUB, SOURCE_CONFLUENCE], confidence=min(0.9, 0.5 + github_score * 0.1), matched_source=SOURCE_GITHUB)

    # Strong Confluence signal
    if confluence_score >= 2 and confluence_score > jira_score and confluence_score > github_score:
        return IntentResult(sources=[SOURCE_CONFLUENCE], confidence=min(0.9, 0.5 + confluence_score * 0.1), matched_source=SOURCE_CONFLUENCE)

    # Mixed signals → search all
    return IntentResult(sources=ALL_SOURCES, confidence=0.5, matched_source=None)
