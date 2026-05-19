from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    cors_origins: str = Field(
        default="http://localhost:8081,http://127.0.0.1:8081",
        alias="CORS_ORIGINS",
    )

    api_sports_key: str | None = Field(default=None, alias="API_SPORTS_KEY")
    api_sports_hockey_base_url: str = Field(
        default="https://v1.hockey.api-sports.io",
        alias="API_SPORTS_HOCKEY_BASE_URL",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
