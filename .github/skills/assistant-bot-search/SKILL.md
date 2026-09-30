---
name: assistant-bot-search
description: "Search your ingested documents via the Assistant Bot RAG pipeline. Returns AI-generated answers with source citations and links. USE FOR: finding documentation, architecture decisions, runbooks, onboarding guides, process docs and team knowledge. DO NOT USE FOR: external web searches, code generation, file editing."
argument-hint: "Natural language question, e.g. 'What are the API rate limits?' or 'What is the onboarding process?'"
---

# Assistant Bot Search Skill

Search your ingested documentation using the Assistant Bot RAG pipeline (local models via Ollama). Returns AI-generated answers grounded in real documents, with source citations linking to the original pages.

---

## MCP Server

**Server name (in `.vscode/mcp.json`):** `assistant-bot-search`
**Local endpoint:** `http://localhost:8000` (Assistant Bot backend must be running via `podman compose up -d`)
**Transport:** stdio (via `mcp_stdio_proxy.py`)

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `search_confluence` | Ask a question → get an AI answer with source citations |
| `list_spaces` | Show which Confluence spaces are ingested |
| `check_health` | Check Assistant Bot component health (backend, Qdrant, Ollama) |
| `ingest_status` | Check whether ingestion is currently running |

---

## Workflow

### Step 1 — Search for an answer

Use the `search_confluence` tool with a natural language question:

```
search_confluence(query="What are the API rate limits?")
```

Optionally filter by space:
```
search_confluence(query="deployment process", space_keys="ENG,IT")
```

### Step 2 — Review the answer and sources

The tool returns:
- An AI-generated answer based on retrieved documentation
- Source citations with page titles, URLs, space keys, and similarity scores
- Text excerpts from matched chunks

### Step 3 — Follow up if needed

Ask follow-up questions — each call is independent (no conversation state in the MCP tool). Be specific in follow-ups:

```
search_confluence(query="How should clients retry after a 429 response?")
```

---

## Prerequisites

Assistant Bot must be running locally:
```bash
.\run.ps1          # Windows
./run.sh           # macOS/Linux
```

Documents must be ingested first. Check with:
```
list_spaces()      # shows ingested spaces
check_health()     # shows component status
```

---

## Tips for Best Results

- **Be specific** — "How should clients retry after a 429 response?" beats "tell me about retries"
- **Use space_keys** — filter to relevant spaces if you know them (e.g. `"ENG"` for engineering docs)
- **Check sources** — the citation URLs link directly to the source pages for full context
- **No results?** — verify documents are ingested with `list_spaces()`. If empty, run ingestion first
