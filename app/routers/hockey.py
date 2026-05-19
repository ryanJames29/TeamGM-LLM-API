import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.schemas.hockey import NhlLeagueResponse, NhlScoresResponse, NhlSyncStatusResponse
from app.services.nhl_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    KEY_SYNC_STATUS,
    build_scores_payload_from_cache,
)
from app.services.redis_store import safe_redis_get_json, safe_redis_hlen

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hockey", tags=["hockey"])


@router.get("/nhl/league", response_model=NhlLeagueResponse)
async def get_nhl_league() -> dict[str, object]:
    """NHL league metadata from Redis (updated hourly by background job)."""
    meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NHL metadata not ready yet. Wait for the standings sync job.",
        )

    return {
        "status": "ok",
        "source": "cache",
        "league": meta.get("league"),
        "updatedAt": meta.get("updatedAt"),
    }


@router.get("/nhl/games", response_model=NhlScoresResponse)
async def get_nhl_games(
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="Center date (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """
    NHL scores for the mobile app.

    Reads from Redis only — zero API-Sports calls per request.
    Data is refreshed by background jobs (minute scores, hourly standings).
    """
    logger.info("NHL games — serving from cache")
    game_date: date | None = None
    if date_param is not None:
        try:
            game_date = date.fromisoformat(date_param)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date must be YYYY-MM-DD",
            ) from exc

    payload = await build_scores_payload_from_cache(settings, center=game_date)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "NHL scores cache is empty. Ensure Redis is running, ENABLE_NHL_JOBS=true, "
                "and API_SPORTS_KEY is set so background jobs can populate data."
            ),
        )

    return payload


@router.get("/nhl/sync-status", response_model=NhlSyncStatusResponse)
async def get_nhl_sync_status() -> dict[str, object]:
    """Operational status for NHL background jobs (dev / monitoring)."""
    status_payload = await safe_redis_get_json(KEY_SYNC_STATUS)
    meta = await safe_redis_get_json(KEY_LEAGUE_META)

    raw_games_count = await safe_redis_hlen(KEY_RAW_GAMES_HASH)

    return {
        "status": "ok",
        "sync": status_payload if isinstance(status_payload, dict) else {},
        "leagueMetaReady": meta is not None,
        "cache": {
            "rawGamesInRedis": raw_games_count,
        },
    }
