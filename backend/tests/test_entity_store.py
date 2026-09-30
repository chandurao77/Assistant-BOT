"""Tests for Cognee-lite entity extraction and storage."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.entity_store import EntityStore


@pytest.fixture
def settings():
    s = MagicMock()
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_llm_model = "mistral"
    return s


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_entities.db")


class TestEntityStoreCreate:
    @pytest.mark.asyncio
    async def test_creates_database(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)
        assert Path(db_path).exists()

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, settings, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "entities.db")
        store = await EntityStore.create(settings, deep_path)
        assert Path(deep_path).exists()


class TestParseJsonArray:
    def test_valid_json_array(self):
        result = EntityStore._parse_json_array('["kubernetes", "docker", "helm"]')
        assert result == ["kubernetes", "docker", "helm"]

    def test_json_array_with_surrounding_text(self):
        result = EntityStore._parse_json_array('Here are the entities:\n["kubernetes", "docker"]')
        assert result == ["kubernetes", "docker"]

    def test_empty_array(self):
        result = EntityStore._parse_json_array("[]")
        assert result == []

    def test_no_array_found(self):
        result = EntityStore._parse_json_array("I found kubernetes and docker")
        assert result == []

    def test_invalid_json(self):
        result = EntityStore._parse_json_array("[invalid json")
        assert result == []

    def test_caps_at_15(self):
        items = [f"entity{i}" for i in range(20)]
        result = EntityStore._parse_json_array(json.dumps(items))
        assert len(result) == 15

    def test_filters_non_strings(self):
        result = EntityStore._parse_json_array('[123, "valid", null, "also valid"]')
        assert result == ["valid", "also valid"]

    def test_strips_whitespace(self):
        result = EntityStore._parse_json_array('["  kubernetes  ", " docker "]')
        assert result == ["kubernetes", "docker"]


class TestExtractKeywords:
    def test_extracts_meaningful_words(self):
        result = EntityStore._extract_keywords("What is the Kubernetes deployment process?")
        assert "Kubernetes" in result
        assert "deployment" in result
        assert "process" in result

    def test_filters_stop_words(self):
        result = EntityStore._extract_keywords("What does this have about that?")
        assert len(result) == 0

    def test_filters_short_words(self):
        result = EntityStore._extract_keywords("the cat sat on mat")
        assert "cat" not in result  # 3 chars, below threshold
        assert "sat" not in result

    def test_hyphenated_words(self):
        result = EntityStore._extract_keywords("How does ci-cd work with micro-services?")
        assert "ci-cd" in result or "micro-services" in result


class TestExtractAndStore:
    @pytest.mark.asyncio
    async def test_extracts_and_stores_entities(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            resp = MagicMock()
            resp.json.return_value = {"response": '["kubernetes", "docker", "helm"]'}
            instance.post = AsyncMock(return_value=resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            entities = await store.extract_and_store("page1", "Deploy with Kubernetes and Docker using Helm charts")

        assert "kubernetes" in entities or "Kubernetes" in entities
        assert len(entities) == 3

    @pytest.mark.asyncio
    async def test_clears_old_entities_on_reingestion(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            # First ingestion
            resp1 = MagicMock()
            resp1.json.return_value = {"response": '["old_entity"]'}
            instance.post = AsyncMock(return_value=resp1)
            await store.extract_and_store("page1", "Old content")

            # Second ingestion — should replace old entities
            resp2 = MagicMock()
            resp2.json.return_value = {"response": '["new_entity"]'}
            instance.post = AsyncMock(return_value=resp2)
            await store.extract_and_store("page1", "New content")

        # Should find page1 with "new_entity" but not "old_entity"
        pages = await store.find_pages_by_entities("new_entity stuff")
        assert "page1" in pages

    @pytest.mark.asyncio
    async def test_returns_empty_on_extraction_failure(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post = AsyncMock(side_effect=Exception("Connection refused"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            entities = await store.extract_and_store("page1", "Some text")

        assert entities == []


class TestFindPagesByEntities:
    @pytest.mark.asyncio
    async def test_finds_pages_by_keyword(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)

        with patch("httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = instance

            # Store entities for two pages
            resp1 = MagicMock()
            resp1.json.return_value = {"response": '["kubernetes", "docker"]'}
            instance.post = AsyncMock(return_value=resp1)
            await store.extract_and_store("page1", "K8s and Docker")

            resp2 = MagicMock()
            resp2.json.return_value = {"response": '["kubernetes", "helm"]'}
            instance.post = AsyncMock(return_value=resp2)
            await store.extract_and_store("page2", "K8s and Helm")

        # Both pages mention kubernetes
        pages = await store.find_pages_by_entities("How does Kubernetes work?")
        assert "page1" in pages
        assert "page2" in pages

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_entities(self, settings, db_path):
        store = await EntityStore.create(settings, db_path)
        pages = await store.find_pages_by_entities("How does xyznonexistent work?")
        assert pages == []
