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
    database_url: str = "postgresql+asyncpg://investlab:investlab@localhost:5432/investlab"
    database_url_sync: str = "postgresql+psycopg2://investlab:investlab@localhost:5432/investlab"

    # Security
    secret_key: str = "changeme"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
