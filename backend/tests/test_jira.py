"""Tests for Jira client and issue-to-chunk conversion."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.jira import JiraClient, issue_to_chunks, _extract_text


# ── ADF text extraction ──────────────────────────────────────────────────────


class TestExtractText:
    def test_none_returns_empty(self):
        assert _extract_text(None) == ""

    def test_plain_string(self):
        assert _extract_text("Hello world") == "Hello world"

    def test_adf_paragraph(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world"},
                    ],
                }
            ],
        }
        assert _extract_text(adf) == "Hello world"

    def test_nested_adf(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Item 1"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Item 2"}],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        result = _extract_text(adf)
        assert "Item 1" in result
        assert "Item 2" in result

    def test_empty_dict(self):
        assert _extract_text({}) == ""


# ── Issue to chunks ──────────────────────────────────────────────────────────


class TestIssueToChunks:
    def _make_issue(self, **overrides):
        issue = {
            "key": "ENG-42",
            "self": "https://myorg.atlassian.net/rest/api/3/issue/12345",
            "fields": {
                "summary": "Fix login redirect bug",
                "description": "Users can't log in after SSO redirect",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Bug"},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Alice"},
                "reporter": {"displayName": "Bob"},
                "labels": ["backend", "auth"],
                "created": "2024-01-15T10:00:00.000+0000",
                "updated": "2024-06-01T14:30:00.000+0000",
                "project": {"key": "ENG", "name": "Engineering"},
                "comment": {"comments": []},
            },
        }
        issue["fields"].update(overrides)
        return issue

    def test_basic_conversion(self):
        issue = self._make_issue()
        chunks = issue_to_chunks(issue)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.page_id == "jira_ENG-42"
        assert chunk.space_key == "__JIRA__"
        assert "Jira: ENG" in chunk.space_name
        assert "ENG-42" in chunk.title
        assert "Fix login redirect bug" in chunk.title
        assert "Bug" in chunk.text
        assert "In Progress" in chunk.text
        assert "Alice" in chunk.text
        assert "backend" in chunk.text
        assert "/browse/ENG-42" in chunk.url

    def test_missing_assignee(self):
        issue = self._make_issue(assignee=None)
        chunks = issue_to_chunks(issue)
        assert "Unassigned" in chunks[0].text

    def test_with_comments(self):
        issue = self._make_issue(
            comment={
                "comments": [
                    {
                        "author": {"displayName": "Charlie"},
                        "body": "This is a comment",
                    }
                ]
            }
        )
        chunks = issue_to_chunks(issue)
        assert "Charlie" in chunks[0].text
        assert "This is a comment" in chunks[0].text

    def test_adf_description(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "ADF description text"}],
                }
            ],
        }
        issue = self._make_issue(description=adf)
        chunks = issue_to_chunks(issue)
        assert "ADF description text" in chunks[0].text

    def test_no_labels(self):
        issue = self._make_issue(labels=[])
        chunks = issue_to_chunks(issue)
        assert "Labels:" not in chunks[0].text

    def test_last_modified_parsed(self):
        issue = self._make_issue()
        chunks = issue_to_chunks(issue)
        assert chunks[0].last_modified.year == 2024


# ── JiraClient init ──────────────────────────────────────────────────────────


class TestJiraClientInit:
    def test_init(self):
        settings = MagicMock()
        settings.jira_base_url = "https://myorg.atlassian.net"
        settings.jira_email = "test@example.com"
        settings.jira_api_token = "token123"
        settings.jira_projects = ["ENG", "MESH"]
        settings.jira_max_issues = 100

        client = JiraClient(settings)
        assert client._base_url == "https://myorg.atlassian.net"
        assert client._projects == ["ENG", "MESH"]
        assert client._max_issues == 100
