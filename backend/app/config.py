"""Application settings, read from environment / the repo-root .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    database_url: str = ""  # empty -> SQLite file under data_dir
    scheduler_enabled: bool = True
    refresh_hour: int = 23
    refresh_minute: int = 30
    startup_refresh_max_age_hours: int = 18
    http_timeout_seconds: float = 30.0
    # Secrets: only from .env / environment. Never stored in the DB, returned by the API or logged.
    anthropic_api_key: str = ""
    groww_enabled: bool = False
    groww_api_key: str = ""
    groww_totp_secret: str = ""

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'investments.db'}"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()
