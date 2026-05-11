"""Runtime configuration loaded from environment via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `env_ignore_empty=True`: a shell var like `ANTHROPIC_API_KEY=""` (empty
    # string) is treated as unset, so the value in `.env` is not silently
    # shadowed by a sandboxed/harness shell that injects empty vars.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")

    dataforseo_login: str = Field(default="", alias="DATAFORSEO_LOGIN")
    dataforseo_password: str = Field(default="", alias="DATAFORSEO_PASSWORD")
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")

    max_cost_usd: float = Field(default=3.0, alias="MAX_COST_USD")
    output_dir: Path = Field(default=Path("./briefs"), alias="OUTPUT_DIR")
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
