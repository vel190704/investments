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
    source_timeout_seconds: float = 25.0  # news/announcement feeds (polite client), per request
    source_timeouts: dict[str, float] = {}  # per-host override, e.g. {"nsearchives.nseindia.com": 40}
    # Secrets: only from .env / environment. Never stored in the DB, returned by the API or logged.
    anthropic_api_key: str = ""
    claude_model: str = ""  # default LLM model (Settings can override)
    # Phase 6: deployment and accounts
    environment: str = "development"  # development | preview | production
    auth_mode: str = "dev"  # dev (local fake user; refused in production) | supabase
    dev_user_email: str = "owner@localhost"  # dev mode: the local user (owner of migrated single-user data)
    admin_emails: str = ""  # comma-separated; these users are admins (and always allowed)
    supabase_url: str = ""  # https://<project>.supabase.co
    supabase_jwt_secret: str = ""  # legacy HS256 secret (only if the project still uses it)
    supabase_jwt_audience: str = "authenticated"
    supabase_service_role_key: str = ""  # optional, server-side only: sends invite emails from the admin page
    field_encryption_key: str = ""  # Fernet key for users' own AI keys (optional feature)
    # Logging (app/logging_config.py)
    log_level: str = "INFO"
    log_format: str = "kv"  # kv (key=value lines) | json
    log_dir: Path = REPO_ROOT / "logs"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'investments.db'}"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()
