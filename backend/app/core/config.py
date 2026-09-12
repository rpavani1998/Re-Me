from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://reme:reme@localhost:5432/reme"
    app_env: str = "development"
    demo_mode: bool = False
    api_token: str = ""
    google_client_id: str = ""
    user_id: str = "demo-user"
    llm_provider: Literal["openai", "openrouter"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    embedding_model: str = "text-embedding-3-small"
    allowed_origins: list[str] = ["http://localhost:3000"]
    ambiguous_api_key: str = ""
    ambiguous_calendar_id: str = ""
    ambiguous_owner_email: str = ""
    exa_api_key: str = ""
    trigger_secret_key: str = ""
    trigger_callback_token: str = ""
    public_api_url: str = "http://localhost:8000"
    context_ttl_minutes: int = 30

    def validate_runtime(self):
        if not self.demo_mode:
            if self.llm_provider not in ("openai", "openrouter"):
                raise RuntimeError(f"LLM_PROVIDER must be 'openai' or 'openrouter', got '{self.llm_provider}'")
            required_key = self.openrouter_api_key if self.llm_provider == "openrouter" else self.openai_api_key
            if not required_key:
                raise RuntimeError(f"Set {'OPENROUTER_API_KEY' if self.llm_provider == 'openrouter' else 'OPENAI_API_KEY'} or explicitly enable DEMO_MODE")
        if self.app_env == "production":
            if self.demo_mode or (self.api_token and len(self.api_token) < 32):
                raise RuntimeError("Production requires live providers; optional API_TOKEN must be at least 32 characters")
            if not self.database_url.startswith("postgresql"):
                raise RuntimeError("Production requires PostgreSQL")


@lru_cache
def settings():
    return Settings()
