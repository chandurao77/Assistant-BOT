# IDE Integration (MCP server)

`mcp_stdio_proxy.py` is a small [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI coding assistant in your editor query Assistant Bot. It forwards tool calls to the Assistant Bot backend's HTTP API.

## Tools

| Tool | Purpose |
|------|---------|
| `search_confluence` | Ask a question and get an answer with source citations. Optional `space_keys` filter. |
| `list_spaces` | Show which spaces have been ingested. |
| `check_health` | Report the status of the backend, Qdrant, and Ollama. |
| `ingest_status` | Show whether an ingestion is running. |
| `trigger_ingest` | Start a Confluence ingestion (only useful if you configured your own Confluence site). |
| `push_page` | Index a single page immediately from HTML you already have. |

## Setup

1. Start Assistant Bot (see the main [README](../README.md)) and ingest some documents.
2. Install the MCP library used by the server:

   ```bash
   pip install mcp httpx
   ```

3. Register the server. [.vscode/mcp.json](../.vscode/mcp.json) already does this for VS Code:

   ```json
   {
     "servers": {
       "assistant-bot-search": {
         "type": "stdio",
         "command": "python3",
         "args": ["${workspaceFolder}/mcp_stdio_proxy.py"],
         "env": { "ASSISTANT_BOT_API_URL": "http://localhost:8005" }
       }
     }
   }
   ```

   The compose file publishes the backend on port `8005`, so set `ASSISTANT_BOT_API_URL` to that. The script's built-in default is `http://localhost:8000`.

4. If you set `API_KEY` in `.env`, either export `ASSISTANT_BOT_API_KEY` for the server process or leave the key in the repository's `.env` file; the script reads `API_KEY` from there when `ASSISTANT_BOT_API_KEY` is not set.

## Example prompts for your assistant

- "Use assistant-bot-search to find out how production releases are scheduled."
- "Ask assistant-bot-search what the rate limit is for the public API."
