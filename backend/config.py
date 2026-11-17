"""Application configuration, read from environment variables and `.env`."""

import os
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

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # .env is this project's config file, so it wins over variables that
        # happen to be exported in the shell (e.g. a stray OPENAI_BASE_URL).
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # --- OpenAI -----------------------------------------------------------
    # Optional at import time so the server can start (and report a clear
    # error) before a key is configured.
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # any OpenAI-compatible endpoint
    openai_model: str = "gpt-5.6-terra"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_temperature: Optional[float] = None  # None = model default
    # Comma-separated models to try, in order, when the main model is busy,
    # rate-limited or unavailable.
    openai_fallback_models: str = ""
    # Seconds to wait for one API response before giving up on it.
    openai_timeout: float = 60
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
    # Hosted vector database. When both are set, the knowledge base is stored
    # in Upstash Vector instead of the local ChromaDB folder.
    upstash_vector_rest_url: Optional[str] = None
    upstash_vector_rest_token: Optional[str] = None
    collection_name: str = "documents"
    chunk_size: int = 1200  # characters
    chunk_overlap: int = 200  # characters

    # --- Files ------------------------------------------------------------
    templates_dir: str = "./templates"
    # Where uploaded templates are saved (defaults to templates_dir; on
    # Vercel, a temporary folder, because the project folder is read-only).
    template_upload_dir: Optional[str] = None
    output_dir: str = "./output"

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def chroma_path(self) -> Path:
        return self._resolve(self.chroma_db_path)

    @property
    def on_serverless(self) -> bool:
        """True on Vercel (and similar hosts) where only /tmp is writable."""
        return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

    @property
    def uses_upstash(self) -> bool:
        return bool(self.upstash_vector_rest_url and self.upstash_vector_rest_token)

    @property
    def templates_path(self) -> Path:
        return self._resolve(self.templates_dir)

    @property
    def template_upload_path(self) -> Path:
        if self.template_upload_dir:
            return self._resolve(self.template_upload_dir)
        if self.on_serverless:
            return Path("/tmp/templates")
        return self.templates_path

    @property
    def output_path(self) -> Path:
        if self.on_serverless and self.output_dir == "./output":
            return Path("/tmp/output")
        return self._resolve(self.output_dir)

    @property
    def chat_models(self) -> List[str]:
        """Main chat model followed by the fallbacks, without duplicates."""
        models = [self.openai_model] + self.openai_fallback_models.split(",")
        return list(dict.fromkeys(m.strip() for m in models if m.strip()))

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]


settings = Settings()
