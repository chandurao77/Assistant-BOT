"""Unit tests for app.services.local_loader."""
import json
import pytest
from pathlib import Path
from app.services.local_loader import load_local_docs, _title_from_content


class TestTitleFromContent:
    def test_extracts_h1_heading(self):
        assert _title_from_content("# My Title\nBody text") == "My Title"

    def test_extracts_h2_heading(self):
        assert _title_from_content("## Section Title\nBody") == "Section Title"

    def test_falls_back_to_first_line(self):
        assert _title_from_content("First line\nSecond line") == "First line"

    def test_empty_string_returns_none(self):
        assert _title_from_content("") is None

    def test_skips_empty_lines_to_find_heading(self):
        assert _title_from_content("\n\n# Real Title\n") == "Real Title"

    def test_long_first_line_truncated_to_80(self):
        long_line = "A" * 100
        result = _title_from_content(long_line)
        assert len(result) == 80


class TestLoadLocalDocs:
    def test_loads_markdown_file(self, tmp_path: Path):
        md = tmp_path / "doc.md"
        md.write_text("# Test Doc\n\nSome content here.", encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 1
        assert pages[0].title == "Test Doc"
        assert "Some content" in pages[0].body_html

    def test_loads_txt_file(self, tmp_path: Path):
        txt = tmp_path / "notes.txt"
        txt.write_text("Plain text content.", encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 1
        assert "Plain text content" in pages[0].body_html

    def test_loads_json_file_single_object(self, tmp_path: Path):
        data = {"id": "doc1", "title": "JSON Doc", "content": "JSON content here."}
        (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 1
        assert pages[0].title == "JSON Doc"
        assert pages[0].page_id == "doc1"

    def test_loads_json_file_array(self, tmp_path: Path):
        data = [
            {"id": "a", "title": "Doc A", "content": "Content A"},
            {"id": "b", "title": "Doc B", "content": "Content B"},
        ]
        (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 2
        titles = {p.title for p in pages}
        assert titles == {"Doc A", "Doc B"}

    def test_skips_empty_json_content(self, tmp_path: Path):
        data = [{"id": "empty", "title": "Empty", "content": ""}]
        (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 0

    def test_ignores_unsupported_file_types(self, tmp_path: Path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "data.csv").write_text("a,b,c", encoding="utf-8")
        (tmp_path / "doc.md").write_text("# Valid\nContent", encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert len(pages) == 1

    def test_raises_if_folder_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_local_docs("/nonexistent/path/xyz")

    def test_returns_empty_for_empty_folder(self, tmp_path: Path):
        pages = load_local_docs(tmp_path)
        assert pages == []

    def test_space_key_defaults_to_local(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("# Doc\nContent", encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert pages[0].space_key == "LOCAL"

    def test_json_custom_space_key(self, tmp_path: Path):
        data = {"title": "ENG Doc", "content": "text", "space_key": "ENG"}
        (tmp_path / "d.json").write_text(json.dumps([data]), encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert pages[0].space_key == "ENG"

    def test_page_id_generated_for_md(self, tmp_path: Path):
        (tmp_path / "my_doc.md").write_text("# Doc\nContent", encoding="utf-8")
        pages = load_local_docs(tmp_path)
        assert pages[0].page_id == "local_my_doc"
