from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str
    api_key: str
    model: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")

    # LLM
    llm_provider: Literal["openrouter", "gemini", "none"] = "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-3.5-flash-lite"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_timeout_seconds: float = 60
    llm_max_concurrency: int = 2
    llm_max_calls_per_day: int = 200

    # Feltöltés és tárolás
    max_upload_mb: int = 20
    database_url: str = "sqlite:///./data/app.db"
    data_dir: str = "./data"

    # MNB
    mnb_url: str = "http://www.mnb.hu/arfolyamok.asmx"
    mnb_timeout_seconds: float = 20

    # Saját cég
    own_company_name: str = "Nordwind Solutions Kft."
    own_tax_number: str = "26481937-2-43"
    own_eu_vat: str = "HU26481937"

    @property
    def llm(self) -> LlmConfig | None:
        if self.llm_provider == "openrouter":
            cfg = LlmConfig("openrouter", self.openrouter_base_url, self.openrouter_api_key, self.openrouter_model)
        elif self.llm_provider == "gemini":
            cfg = LlmConfig("gemini", self.gemini_base_url, self.gemini_api_key, self.gemini_model)
        else:
            return None
        return cfg if cfg.api_key.strip() else None

    @property
    def llm_enabled(self) -> bool:
        return self.llm is not None

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()