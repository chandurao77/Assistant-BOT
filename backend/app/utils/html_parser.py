"""Strip Confluence HTML storage format to clean plain text."""
from __future__ import annotations
import re
from bs4 import BeautifulSoup


# Confluence macros that carry useful text
_KEEP_MACRO_BODIES = {"info", "note", "warning", "tip", "panel", "expand"}


def html_to_text(html: str) -> str:
    """
    Convert Confluence HTML storage format → clean plain text.

    Handles:
    - Structured macros (code blocks kept, layout stripped)
    - Tables → pipe-delimited text
    - Lists → bullet lines
    - Headings → prefixed with level marker so hierarchy is preserved
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Remove script / style / navigation noise
    for tag in soup.find_all(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Replace code macro bodies with fenced block notation
    for code_block in soup.find_all("ac:structured-macro", attrs={"ac:name": "code"}):
        body = code_block.find("ac:plain-text-body")
        code_text = body.get_text() if body else ""
        code_block.replace_with(f"\n```\n{code_text}\n```\n")

    # Drop layout / column macros but keep their text children
    for macro in soup.find_all("ac:structured-macro"):
        macro_name = macro.get("ac:name", "")
        if macro_name in _KEEP_MACRO_BODIES:
            # Promote children
            macro.unwrap()
        else:
            macro.decompose()

    # Convert tables to readable pipe-delimited format
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["th", "td"])]
            rows.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(rows) + "\n")

    # Convert headings
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            prefix = "#" * level
            h.replace_with(f"\n{prefix} {h.get_text(strip=True)}\n")

    # Convert list items
    for li in soup.find_all("li"):
        li.replace_with(f"\n• {li.get_text(separator=' ', strip=True)}")

    # Preserve images as markdown references
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "").strip() or img.get("title", "").strip() or "image"
        if src:
            # Skip tiny tracking pixels and spacers
            width = img.get("width", "")
            height = img.get("height", "")
            if width and height:
                try:
                    if int(width) <= 2 and int(height) <= 2:
                        img.decompose()
                        continue
                except (ValueError, TypeError):
                    pass
            img.replace_with(f"\n![{alt}]({src})\n")
        else:
            img.decompose()

    text = soup.get_text(separator="\n")

    # Normalise whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()

    return text


# Match Confluence Cloud:  /wiki/spaces/SPACE/pages/PAGE_ID/...
# Match Confluence Server: /pages/viewpage.action?pageId=PAGE_ID
#                          /pages/viewpage.action?pageId=PAGE_ID&...
_CONFLUENCE_LINK_PATTERNS = [
    re.compile(r"/wiki/spaces/[^/]+/pages/(\d+)", re.IGNORECASE),
    re.compile(r"/pages/viewpage\.action\?(?:[^&]*&)*pageId=(\d+)", re.IGNORECASE),
]


def extract_confluence_links(html: str) -> list[str]:
    """
    Extract internal Confluence page IDs from ``<a href>`` tags.

    Matches hrefs of the form:
    - ``/wiki/spaces/SPACE/pages/PAGE_ID/...``  (Confluence Cloud)
    - ``/pages/viewpage.action?pageId=PAGE_ID`` (Confluence Server)

    Returns a deduplicated list of page ID strings.
    External links and non-page hrefs are ignored.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        for pattern in _CONFLUENCE_LINK_PATTERNS:
            m = pattern.search(href)
            if m:
                seen.add(m.group(1))
                break
    return list(seen)
