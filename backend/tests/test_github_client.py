"""Tests for GitHub client and document conversion functions."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.github_client import GitHubClient, file_to_chunk, pr_to_chunk


# ── file_to_chunk ────────────────────────────────────────────────────────────


class TestFileToChunk:
    def test_basic_conversion(self):
        chunk = file_to_chunk("org/repo", "README.md", "# Hello\n\nWorld")

        assert chunk.page_id == "github_org_repo_README.md"
        assert chunk.space_key == "__GITHUB__"
        assert "GitHub: org/repo" in chunk.space_name
        assert "org/repo: README.md" in chunk.title
        assert "Hello" in chunk.text
        assert "World" in chunk.text
        assert "github.com/org/repo/blob/HEAD/README.md" in chunk.url
        assert chunk.chunk_index == 0
        assert chunk.total_chunks == 1

    def test_nested_path(self):
        chunk = file_to_chunk("org/repo", "src/utils/helpers.py", "def helper(): pass")
        assert "src_utils_helpers.py" in chunk.page_id
        assert "src/utils/helpers.py" in chunk.title

    def test_custom_repo_url(self):
        chunk = file_to_chunk("org/repo", "file.py", "code", repo_url="https://github.enterprise.com/org/repo")
        assert "github.enterprise.com" in chunk.url


# ── pr_to_chunk ──────────────────────────────────────────────────────────────


class TestPrToChunk:
    def _make_pr(self, **overrides):
        pr = {
            "number": 42,
            "title": "Add feature X",
            "body": "This PR adds feature X for better performance",
            "state": "closed",
            "merged_at": "2024-06-01T12:00:00Z",
            "user": {"login": "alice"},
            "labels": [{"name": "enhancement"}, {"name": "approved"}],
            "updated_at": "2024-06-01T14:00:00Z",
            "html_url": "https://github.com/org/repo/pull/42",
        }
        pr.update(overrides)
        return pr

    def test_basic_conversion(self):
        pr = self._make_pr()
        chunk = pr_to_chunk("org/repo", pr)

        assert chunk is not None
        assert chunk.page_id == "github_pr_org_repo_42"
        assert chunk.space_key == "__GITHUB__"
        assert "PR #42" in chunk.title
        assert "Add feature X" in chunk.title
        assert "alice" in chunk.text
        assert "merged" in chunk.text
        assert "enhancement" in chunk.text
        assert chunk.url == "https://github.com/org/repo/pull/42"

    def test_open_pr(self):
        pr = self._make_pr(state="open", merged_at=None)
        chunk = pr_to_chunk("org/repo", pr)
        assert "open" in chunk.text

    def test_no_title_returns_none(self):
        pr = self._make_pr(title="")
        assert pr_to_chunk("org/repo", pr) is None

    def test_no_body(self):
        pr = self._make_pr(body=None)
        chunk = pr_to_chunk("org/repo", pr)
        assert chunk is not None

    def test_no_labels(self):
        pr = self._make_pr(labels=[])
        chunk = pr_to_chunk("org/repo", pr)
        assert "Labels:" not in chunk.text

    def test_long_body_truncated(self):
        long_body = "x" * 5000
        pr = self._make_pr(body=long_body)
        chunk = pr_to_chunk("org/repo", pr)
        # Body should be truncated to 3000 chars
        assert len(chunk.text) < 4000

    def test_last_modified_parsed(self):
        pr = self._make_pr()
        chunk = pr_to_chunk("org/repo", pr)
        assert chunk.last_modified.year == 2024


# ── GitHubClient init ────────────────────────────────────────────────────────


class TestGitHubClientInit:
    def test_init(self):
        settings = MagicMock()
        settings.github_token = "ghp_test123"
        settings.github_repos = ["org/repo1", "org/repo2"]
        settings.github_max_files = 500
        settings.github_file_extensions = [".md", ".py"]

        client = GitHubClient(settings)
        assert client._token == "ghp_test123"
        assert client._repos == ["org/repo1", "org/repo2"]
        assert ".md" in client._allowed_extensions
