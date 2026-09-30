"""Unit tests for app.utils.html_parser."""
import pytest
from app.utils.html_parser import html_to_text, extract_confluence_links


class TestHtmlToText:
    def test_empty_string(self):
        assert html_to_text("") == ""

    def test_plain_text_passthrough(self):
        result = html_to_text("<p>Hello world</p>")
        assert "Hello world" in result

    def test_strips_script_tags(self):
        html = "<p>Content</p><script>alert('xss')</script>"
        result = html_to_text(html)
        assert "alert" not in result
        assert "Content" in result

    def test_strips_style_tags(self):
        html = "<p>Content</p><style>body { color: red; }</style>"
        result = html_to_text(html)
        assert "color: red" not in result
        assert "Content" in result

    def test_headings_preserved(self):
        html = "<h1>Title</h1><h2>Subtitle</h2><p>Body text</p>"
        result = html_to_text(html)
        assert "Title" in result
        assert "Subtitle" in result
        assert "Body text" in result

    def test_heading_markers_added(self):
        result = html_to_text("<h1>Main Heading</h1>")
        assert "# Main Heading" in result

    def test_h2_marker(self):
        result = html_to_text("<h2>Section</h2>")
        assert "## Section" in result

    def test_list_items_converted(self):
        html = "<ul><li>Item one</li><li>Item two</li></ul>"
        result = html_to_text(html)
        assert "Item one" in result
        assert "Item two" in result
        assert "•" in result

    def test_table_converted_to_pipe_format(self):
        html = """
        <table>
          <tr><th>Name</th><th>Value</th></tr>
          <tr><td>Alpha</td><td>1</td></tr>
        </table>
        """
        result = html_to_text(html)
        assert "Name" in result
        assert "Value" in result
        assert "|" in result

    def test_multiple_blank_lines_collapsed(self):
        html = "<p>A</p><p></p><p></p><p></p><p>B</p>"
        result = html_to_text(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result

    def test_code_block_macro(self):
        html = """
        <ac:structured-macro ac:name="code">
          <ac:plain-text-body>print("hello")</ac:plain-text-body>
        </ac:structured-macro>
        """
        result = html_to_text(html)
        assert 'print("hello")' in result
        assert "```" in result

    def test_confluence_info_macro_unwrapped(self):
        html = """
        <ac:structured-macro ac:name="info">
          <ac:rich-text-body><p>Important note</p></ac:rich-text-body>
        </ac:structured-macro>
        """
        result = html_to_text(html)
        assert "Important note" in result

    def test_unknown_macro_removed(self):
        html = """
        <ac:structured-macro ac:name="jira">
          <ac:parameter>PROJ-123</ac:parameter>
        </ac:structured-macro>
        <p>After macro</p>
        """
        result = html_to_text(html)
        assert "After macro" in result

    def test_whitespace_normalized(self):
        html = "<p>Word   with    extra    spaces</p>"
        result = html_to_text(html)
        assert "  " not in result


class TestExtractConfluenceLinks:
    def test_empty_html_returns_empty_list(self):
        assert extract_confluence_links("") == []

    def test_none_like_input_returns_empty_list(self):
        assert extract_confluence_links(None) == []

    def test_extracts_internal_page_link(self):
        html = '<a href="/wiki/spaces/ENG/pages/12345678/Some+Title">Link</a>'
        result = extract_confluence_links(html)
        assert result == ["12345678"]

    def test_extracts_multiple_links(self):
        html = """
        <a href="/wiki/spaces/ENG/pages/111/PageA">A</a>
        <a href="/wiki/spaces/HR/pages/222/PageB">B</a>
        """
        result = extract_confluence_links(html)
        assert set(result) == {"111", "222"}

    def test_deduplicates_repeated_links(self):
        html = """
        <a href="/wiki/spaces/ENG/pages/999/Page">First</a>
        <a href="/wiki/spaces/ENG/pages/999/Page">Duplicate</a>
        """
        result = extract_confluence_links(html)
        assert result.count("999") == 1

    def test_ignores_external_links(self):
        html = '<a href="https://external.example.com/page">External</a>'
        result = extract_confluence_links(html)
        assert result == []

    def test_ignores_relative_non_wiki_links(self):
        html = '<a href="/spaces/ENG/pages/12345/title">Wrong path</a>'
        result = extract_confluence_links(html)
        assert result == []

    def test_no_links_returns_empty_list(self):
        html = "<p>No links here at all</p>"
        result = extract_confluence_links(html)
        assert result == []
