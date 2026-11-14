"""Application configuration, read from environment variables and `.env`."""

from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    # --- OpenAI -----------------------------------------------------------
    # Optional at import time so the server can start (and report a clear
    # error) before a key is configured.
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # any OpenAI-compatible endpoint
    openai_model: str = "gpt-5.6-terra"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_temperature: Optional[float] = None  # None = model default
    max_output_tokens: int = 2000

    # --- Server -----------------------------------------------------------
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    cors_origins: str = "*"  # comma separated list, or "*"
    # If set, every API call must send it in the `X-API-Key` header.
    api_key: Optional[str] = None
    max_upload_mb: int = 20

    # --- RAG --------------------------------------------------------------
    chroma_db_path: str = "./chroma_data"
    collection_name: str = "documents"
    chunk_size: int = 1200  # characters
    chunk_overlap: int = 200  # characters

    # --- Files ------------------------------------------------------------
    templates_dir: str = "./templates"
    output_dir: str = "./output"

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def chroma_path(self) -> Path:
        return self._resolve(self.chroma_db_path)

    @property
    def templates_path(self) -> Path:
        return self._resolve(self.templates_dir)

    @property
    def output_path(self) -> Path:
        return self._resolve(self.output_dir)

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]


settings = Settings()
