"""Configuration management for RAG Chatbot Backend"""

import json
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Server Configuration
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_TEMPERATURE: float = 0.7

    # Vector Database
    VECTOR_DB_PATH: str = str(DATA_DIR / "vectordb")
    VECTOR_DB_TYPE: str = "chromadb"

    # Database
    DATABASE_URL: str = f"sqlite:///{DATA_DIR / 'app.db'}"

    # RAG Configuration
    MAX_RETRIEVED_DOCS: int = 5
    CONFIDENCE_THRESHOLD: float = 0.7
    MAX_TOKENS: int = 1024
    CONTEXT_WINDOW: int = 5

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173"
    ]

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: bool | str | None) -> bool | str | None:
        """Accept common environment values like `debug` and `release`."""
        if isinstance(value, bool) or value is None:
            return value

        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "production", "prod"}:
            return False

        return value

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: str | List[str]) -> List[str]:
        """Support JSON arrays and comma-separated origin lists."""
        if isinstance(value, list):
            return value
        if not value:
            return []

        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)

        return [origin.strip() for origin in stripped.split(",") if origin.strip()]


settings = Settings()
