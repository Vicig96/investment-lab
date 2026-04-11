from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "investment-lab"
    env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    # Default → SQLite for zero-config local dev.
    # Override in .env with postgresql+asyncpg://... for production.
    database_url: str = "sqlite+aiosqlite:///./investlab.db"
    database_url_sync: str = "sqlite:///./investlab.db"

    # Security
    secret_key: str = "changeme"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
