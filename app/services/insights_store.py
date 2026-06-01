import asyncio
import logging
from datetime import datetime, timezone
from typing import cast

from supabase import Client, create_client

from app.config import Settings
from app.types import JsonObject

logger = logging.getLogger(__name__)

TABLE_HOME_INSIGHTS = "home_insight_snapshots"
TABLE_USER_FAVORITE_TEAMS = "user_favorite_teams"


class InsightsStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None
        if settings.supabase_enabled:
            project_url = settings.supabase_url_normalized or ""
            self._client = create_client(
                project_url,
                settings.supabase_service_role_key or "",
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def load_favorite_teams(self, user_id: str) -> list[JsonObject]:
        if not self._client:
            return []

        def _read() -> list[JsonObject]:
            response = (
                self._client.table(TABLE_USER_FAVORITE_TEAMS)
                .select(
                    "team_id, sort_order, teams (league, api_sports_team_id, name, abbreviation)"
                )
                .eq("user_id", user_id)
                .order("sort_order")
                .execute()
            )
            return cast(list[JsonObject], response.data or [])

        return await asyncio.to_thread(_read)

    async def load_latest_snapshot(self, user_id: str) -> JsonObject | None:
        if not self._client:
            return None

        def _read() -> JsonObject | None:
            response = (
                self._client.table(TABLE_HOME_INSIGHTS)
                .select("id, payload, generated_at, facts_as_of, run_type")
                .eq("user_id", user_id)
                .order("generated_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = cast(list[JsonObject], response.data or [])
            return rows[0] if rows else None

        return await asyncio.to_thread(_read)

    async def save_snapshot(
        self,
        user_id: str,
        payload: JsonObject,
        *,
        run_type: str = "manual",
        facts_as_of: str | None = None,
    ) -> None:
        if not self._client:
            return

        row: JsonObject = {
            "user_id": user_id,
            "payload": payload,
            "run_type": run_type,
            "facts_as_of": facts_as_of,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        def _write() -> None:
            self._client.table(TABLE_HOME_INSIGHTS).insert(row).execute()

        await asyncio.to_thread(_write)
        logger.info("Saved home insight snapshot for user %s", user_id)
