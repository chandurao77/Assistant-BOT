"""Tests for the file parser service."""
from __future__ import annotations

import pytest

from app.services.file_parser import allowed_extension, parse_file


class TestAllowedExtension:
    def test_txt_allowed(self):
        assert allowed_extension("notes.txt") is True

    def test_md_allowed(self):
        assert allowed_extension("README.md") is True

    def test_pdf_allowed(self):
        assert allowed_extension("report.pdf") is True

    def test_docx_allowed(self):
        assert allowed_extension("doc.docx") is True

    def test_exe_rejected(self):
        assert allowed_extension("virus.exe") is False

    def test_py_rejected(self):
        assert allowed_extension("script.py") is False

    def test_no_extension_rejected(self):
        assert allowed_extension("noext") is False

    def test_case_insensitive(self):
        assert allowed_extension("FILE.TXT") is True
        assert allowed_extension("Report.PDF") is True


class TestParseTxt:
    def test_parse_plain_text(self):
        content = b"Hello world\nLine two"
        result = parse_file("test.txt", content)
        assert "Hello world" in result
        assert "Line two" in result

    def test_parse_markdown(self):
        content = b"# Heading\n\nSome paragraph text."
        result = parse_file("readme.md", content)
        assert "Heading" in result
        assert "paragraph" in result

    def test_empty_txt_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_file("empty.txt", b"")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_file("blank.txt", b"   \n  \t  ")


class TestParseUnsupported:
    def test_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported"):
            parse_file("data.csv", b"col1,col2")

    def test_exe_rejected(self):
        with pytest.raises(ValueError, match="Unsupported"):
            parse_file("app.exe", b"\x00\x01")
