"""
Central configuration using pydantic-settings.
All values are read from environment variables / .env file.

Secrets support:
  Any config field can be loaded from a file by setting <FIELD>_FILE env var.
  Example: JWT_SECRET_FILE=/run/secrets/jwt_secret
  This enables container secrets, Kubernetes secret volumes, and Vault agent injection.
"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

# Only mount container secrets dir when it actually exists (avoids warnings on Windows/local dev)
_SECRETS_DIR = "/run/secrets" if Path("/run/secrets").is_dir() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        secrets_dir=_SECRETS_DIR,
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "Assistant Bot"
    environment: str = Field(default="production", pattern="^(development|production|test)$")
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ── Security ─────────────────────────────────────────────────────────
    # Shared secret for API access. Set to a non-empty string to enable auth.
    # Leave empty to disable auth (default, safe for local dev).
    api_key: str = Field(default="", description="Shared API key for X-API-Key header auth. Empty = disabled.")

    # ── JWT Authentication ────────────────────────────────────────────────
    # Secret key for signing JWT tokens. MUST be set to a strong random value in production.
    jwt_secret: str = Field(default="assistant-bot-dev-secret-change-me", description="Secret key for JWT token signing.")
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = Field(default=24, ge=1, le=720, description="JWT token expiry in hours.")

    # ── Rate limiting ─────────────────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = Field(default=30, ge=1, le=1000, description="Max chat requests per IP per minute.")

    # ── LLM behaviour ────────────────────────────────────────────────────
    # Override the default system prompt. Leave empty to use the built-in prompt.
    llm_system_prompt: str = Field(default="", description="Custom system prompt for the LLM. Overrides the default if set.")

    # ── Maintenance ───────────────────────────────────────────────────────
    # Delete conversations older than this many days (0 = keep forever).
    conversation_max_age_days: int = Field(default=90, ge=0, description="Prune conversations older than N days. 0 = disabled.")
    # Auto-trigger local ingest every N hours (0 = disabled).
    ingest_auto_interval_hours: float = Field(default=0, ge=0, description="Auto-ingest interval in hours. 0 = disabled.")

    # ── Confluence ────────────────────────────────────────────────────────
    # Optional for local/dev testing — only required when using Confluence ingestion
    confluence_base_url: str = Field(default="", description="e.g. https://your-site.atlassian.net")
    confluence_email: str = Field(default="", description="Atlassian account email (used for Basic auth only)")
    confluence_api_token: str = Field(default="", description="Atlassian API token or PAT")
    confluence_auth_type: str = Field(
        default="basic",
        pattern="^(basic|bearer)$",
        description="Auth method: 'basic' (email:token) or 'bearer' (PAT/service-account token).",
    )
    confluence_space_keys: list[str] = Field(
        default=["~"],
        description="Space keys to ingest. Use ['~'] for all spaces.",
    )
    confluence_page_limit: int = Field(default=500, ge=1, le=50000)

    # ── Qdrant ────────────────────────────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "confluence_docs"
    qdrant_vector_size: int = 768  # nomic-embed-text output dim

    # ── Ollama (local LLM + embeddings) ───────────────────────────────────────
    # All generation and embedding runs on local models served by Ollama.
    ollama_base_url: str = "http://ollama:11434"
    ollama_llm_model: str = "mistral-nemo"     # Mistral Nemo 12B — better formatting
    ollama_rerank_model: str = ""              # Dedicated reranker model (empty = use ollama_llm_model)
    ollama_embed_model: str = "nomic-embed-text"
    ollama_connect_timeout: int = 10   # seconds — fail fast if Ollama is down
    ollama_read_timeout: int = 600     # seconds — CPU inference can take 10+ min on first load

    # ── Entity Extraction (Cognee-lite) ────────────────────────────────────
    entity_extraction_enabled: bool = True

    # ── Re-ranking ────────────────────────────────────────────────────────
    rerank_enabled: bool = True
    rerank_top_n: int = Field(default=10, ge=1, le=20, description="Number of top chunks to keep after re-ranking.")

    # ── BM25 Hybrid Search ────────────────────────────────────────────────
    # When enabled, replaces binary keyword match with proper BM25
    # term-frequency scoring for the keyword leg of hybrid search.
    bm25_enabled: bool = True

    # ── Contextual Chunking ────────────────────────────────────────────────
    # Prepends page title, space name, and section heading to each chunk
    # before embedding.  Improves retrieval by giving the embedder and
    # keyword search richer context.  Raw text is preserved separately
    # for citation display.
    contextual_chunking_enabled: bool = True

    # ── Content Guardrail ─────────────────────────────────────────────────
    # Regex-based PII/secret redaction applied to retrieved chunks before
    # they are injected into the LLM prompt.  Prevents credential leakage.
    content_guardrail_enabled: bool = True

    # ── Semantic Cache ─────────────────────────────────────────────────────
    # Caches LLM answers keyed by question similarity (via Qdrant collection).
    # A cache HIT skips embedding search + LLM generation entirely.
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = Field(
        default=0.97, ge=0.80, le=1.0,
        description="Cosine similarity threshold for a cache hit. Higher = stricter matching.",
    )
    semantic_cache_ttl: int = Field(
        default=1800, ge=60, le=86400,
        description="Cache entry time-to-live in seconds (default 30 min).",
    )

    # ── Redis (Future — not wired into services yet) ──────────────────────────
    # When enabled, Redis will serve as a shared cache layer across replicas.
    # Currently disabled — the app works without Redis.
    redis_enabled: bool = False
    redis_url: str = "redis://redis:6379/0"
    redis_ttl: int = Field(
        default=3600, ge=60, le=86400,
        description="Default Redis cache TTL in seconds.",
    )

    # ── Slack Bot Integration ─────────────────────────────────────────────────
    # Create a Slack App at https://api.slack.com/apps with:
    #   - Bot Token Scopes: chat:write, app_mentions:read, commands
    #   - Event Subscriptions: app_mention, message.im
    #   - Slash Commands: /assistant
    #   - Messaging endpoint: https://<your-domain>/api/slack/events
    slack_bot_token: str = Field(default="", description="Slack Bot User OAuth Token (xoxb-...)")
    slack_signing_secret: str = Field(default="", description="Slack app signing secret for request verification.")
    slack_enabled: bool = Field(default=False, description="Enable Slack bot integration.")

    # ── Microsoft Teams Bot Integration ────────────────────────────────────────
    # Register a bot at https://dev.botframework.com or via Azure Bot Service.
    #   - Messaging endpoint: https://<your-domain>/api/teams/messages
    #   - App ID and Secret from Azure AD app registration
    teams_app_id: str = Field(default="", description="Azure AD App (Bot) ID.")
    teams_app_secret: str = Field(default="", description="Azure AD App secret for bot auth.")
    teams_enabled: bool = Field(default=False, description="Enable Microsoft Teams bot integration.")

    # ── ELK Stack (Observability) ─────────────────────────────────────────────
    # When enabled, backend sends structured logs to Logstash via TCP:5000.
    # Start ELK with:  podman compose --profile elk up -d
    elk_enabled: bool = False

    # ── OpenTelemetry (Distributed Tracing + Metrics) ─────────────────────────
    # When enabled, exports traces to an OTLP collector (Jaeger, Tempo, etc.).
    # Prometheus /metrics endpoint is always available regardless of this setting.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4317",
        description="OTLP gRPC endpoint for trace export.",
    )
    # ── Database (PostgreSQL — optional, for multi-replica scaling) ──────────
    # When set, uses PostgreSQL instead of SQLite for conversations, feedback,
    # analytics, and page index. Required for horizontal scaling (multiple backend replicas).
    # Start PostgreSQL with:  podman compose --profile postgres up -d
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    database_url: str = Field(
        default="",
        description="PostgreSQL connection URL. Empty = use SQLite (default).",
    )

    # ── SSO / OIDC ────────────────────────────────────────────────────────
    oidc_enabled: bool = False
    oidc_issuer_url: str = Field(default="", description="OIDC issuer URL (e.g. https://login.microsoftonline.com/{tenant}/v2.0)")
    oidc_client_id: str = Field(default="", description="OIDC client/application ID")
    oidc_client_secret: str = Field(default="", description="OIDC client secret")
    oidc_redirect_uri: str = Field(default="http://localhost:3000/auth/callback", description="OAuth2 redirect URI")
    oidc_group_space_mapping: str = Field(default="{}", description='JSON map of OIDC group to Confluence space keys')
    oidc_jwks_cache_ttl: int = Field(default=3600, ge=60, le=86400, description="JWKS key cache TTL in seconds (stale-while-revalidate).")

    # ── Jira Integration (optional) ─────────────────────────────────
    jira_enabled: bool = False
    jira_base_url: str = Field(default="", description="Jira Cloud URL (e.g. https://your-site.atlassian.net)")
    jira_email: str = Field(default="", description="Atlassian account email (used for Basic auth only)")
    jira_api_token: str = Field(default="", description="Atlassian API token or PAT")
    jira_auth_type: str = Field(
        default="basic",
        pattern="^(basic|bearer)$",
        description="Auth method: 'basic' (email:token) or 'bearer' (PAT/service-account token).",
    )
    jira_projects: list[str] = Field(default=[], description="Jira project keys to ingest (e.g. ['ENG', 'MESH'])")
    jira_max_issues: int = Field(default=1000, ge=1, le=10000, description="Max issues to ingest per project")

    # ── GitHub Integration (optional) ───────────────────────────────
    github_enabled: bool = False
    github_token: str = Field(default="", description="GitHub Personal Access Token")
    github_repos: list[str] = Field(default=[], description="Repos to ingest (e.g. ['org/repo1', 'org/repo2'])")
    github_max_files: int = Field(default=500, ge=1, le=5000, description="Max files to ingest per repo")
    github_file_extensions: list[str] = Field(
        default=[".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json", ".toml"],
        description="File extensions to ingest from GitHub repos",
    )

    # ── RAG ───────────────────────────────────────────────────────────────
    chunk_size: int = 256
    chunk_overlap: int = 64
    retrieval_top_k: int = 10             # 10 sources for good coverage with section-split docs
    retrieval_score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    max_context_tokens: int = 4096
    max_context_words_per_source: int = Field(
        default=400,
        ge=50,
        le=2000,
        description="Max words per source chunk fed to the LLM context.",
    )
    max_history_turns: int = Field(
        default=6,
        ge=0,
        le=20,
        description="Number of past user+assistant turns kept in LLM context.",
    )
    graph_hop_depth: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Graph expansion hops after retrieval. 0 = disabled (pure RAG).",
    )
    graph_max_expansion: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Max additional linked pages fetched during graph expansion.",
    )
    llm_max_sources: int = Field(
        default=15,
        ge=1,
        le=20,
        description="Max source chunks fed to the LLM prompt. Graph-expanded sources beyond this limit still appear as citations.",
    )
    ollama_num_ctx: int = Field(
        default=4096,
        ge=512,
        le=32768,
        description="Ollama KV-cache context window (tokens). Must be larger than your typical prompt size.",
    )

    @model_validator(mode="before")
    @classmethod
    def load_file_secrets(cls, values: dict) -> dict:
        """Load secrets from files (<FIELD>_FILE env vars).

        Enables container secrets, K8s secret volumes, Vault agent injection.
        Example: JWT_SECRET_FILE=/run/secrets/jwt_secret → reads file → sets jwt_secret
        """
        import os
        _SECRET_FIELDS = ["jwt_secret", "api_key", "confluence_api_token", "database_url",
                          "slack_bot_token", "slack_signing_secret", "teams_app_secret",
                          "oidc_client_secret", "jira_api_token", "github_token"]
        for field_name in _SECRET_FIELDS:
            env_key = f"{field_name.upper()}_FILE"
            file_path = os.environ.get(env_key, "")
            if file_path:
                path = Path(file_path)
                if path.is_file():
                    secret_value = path.read_text().strip()
                    if secret_value:
                        values[field_name] = secret_value
        return values

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )

        # Reject default JWT secret in production
        if self.environment == "production" and self.jwt_secret == "assistant-bot-dev-secret-change-me":
            raise ValueError(
                "JWT_SECRET must be set to a strong random value in production. "
                "Do not use the default 'assistant-bot-dev-secret-change-me'."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
