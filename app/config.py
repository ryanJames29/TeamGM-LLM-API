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
    api_sports_baseball_base_url: str = Field(
        default="https://v1.baseball.api-sports.io",
        alias="API_SPORTS_BASEBALL_BASE_URL",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    enable_nhl_jobs: bool = Field(default=True, alias="ENABLE_NHL_JOBS")
    enable_mlb_jobs: bool = Field(default=True, alias="ENABLE_MLB_JOBS")

    # Standings → Supabase (hourly). Scores/stats → Redis (every minute).
    nhl_standings_interval_minutes: int = Field(
        default=60,
        alias="NHL_STANDINGS_INTERVAL_MINUTES",
    )
    nhl_scores_interval_seconds: int = Field(
        default=60,
        alias="NHL_SCORES_INTERVAL_SECONDS",
    )
    nhl_window_refresh_hours: int = Field(
        default=24,
        alias="NHL_WINDOW_REFRESH_HOURS",
    )
    nhl_window_lookback_days: int = Field(default=7, alias="NHL_WINDOW_LOOKBACK_DAYS")
    nhl_window_lookahead_days: int = Field(default=3, alias="NHL_WINDOW_LOOKAHEAD_DAYS")

    mlb_standings_interval_minutes: int = Field(
        default=60,
        alias="MLB_STANDINGS_INTERVAL_MINUTES",
    )
    mlb_scores_interval_seconds: int = Field(
        default=60,
        alias="MLB_SCORES_INTERVAL_SECONDS",
    )
    mlb_window_refresh_hours: int = Field(
        default=24,
        alias="MLB_WINDOW_REFRESH_HOURS",
    )
    mlb_window_lookback_days: int = Field(default=7, alias="MLB_WINDOW_LOOKBACK_DAYS")
    mlb_window_lookahead_days: int = Field(default=3, alias="MLB_WINDOW_LOOKAHEAD_DAYS")

    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_service_role_key: str | None = Field(
        default=None,
        alias="SUPABASE_SERVICE_ROLE_KEY",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def supabase_url_normalized(self) -> str | None:
        """Project URL only — supabase-py adds /rest/v1 itself."""
        if not self.supabase_url:
            return None
        url = self.supabase_url.strip().rstrip("/")
        if url.endswith("/rest/v1"):
            url = url[: -len("/rest/v1")]
        return url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
