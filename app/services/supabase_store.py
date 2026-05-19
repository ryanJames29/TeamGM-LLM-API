import asyncio
import logging
from typing import cast

from supabase import Client, create_client

from app.config import Settings
from app.types import JsonObject

logger = logging.getLogger(__name__)

TABLE_TEAM_RECORDS = "nhl_team_records"


class SupabaseStore:
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

    async def upsert_team_records(self, season: int, rows: list[JsonObject]) -> None:
        if not self._client or not rows:
            return

        payload = [{**row, "season": season} for row in rows]

        def _write() -> None:
            self._client.table(TABLE_TEAM_RECORDS).upsert(
                payload,
                on_conflict="season,team_id",
            ).execute()

        await asyncio.to_thread(_write)
        logger.info("Upserted %s NHL team records for season %s", len(payload), season)

    async def load_records_map(self, season: int) -> dict[int, JsonObject]:
        if not self._client:
            return {}

        def _read() -> list[JsonObject]:
            response = (
                self._client.table(TABLE_TEAM_RECORDS)
                .select("team_id, team_name, record, standing, position")
                .eq("season", season)
                .execute()
            )
            return cast(list[JsonObject], response.data or [])

        rows = await asyncio.to_thread(_read)
        return {
            int(row["team_id"]): {
                "record": str(row.get("record") or "—"),
                "standing": str(row["standing"]) if row.get("standing") is not None else None,
                "position": int(row["position"]) if row.get("position") is not None else None,
                "teamName": str(row.get("team_name") or ""),
            }
            for row in rows
            if row.get("team_id") is not None
        }
