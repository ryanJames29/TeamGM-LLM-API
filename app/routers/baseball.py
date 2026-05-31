import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.schemas.baseball import MlbGameDetailResponse, MlbLeagueResponse, MlbScoresResponse, MlbSyncStatusResponse
from app.services.mlb_detail import build_mlb_game_detail
from app.services.mlb_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    KEY_SYNC_STATUS,
    build_scores_payload_from_cache,
)
from app.services.redis_store import safe_redis_get_json, safe_redis_hlen

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/baseball", tags=["baseball"])


@router.get("/mlb/league", response_model=MlbLeagueResponse)
async def get_mlb_league() -> dict[str, object]:
    """MLB league metadata from Redis (updated hourly by background job)."""
    meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MLB metadata not ready yet. Wait for the standings sync job.",
        )

    return {
        "status": "ok",
        "source": "cache",
        "league": meta.get("league"),
        "updatedAt": meta.get("updatedAt"),
    }


@router.get("/mlb/games", response_model=MlbScoresResponse)
async def get_mlb_games(
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="Center date (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """MLB scores for the mobile app — Redis only, no API-Sports per request."""
    logger.info("MLB games — serving from cache")
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
                "MLB scores cache is empty. Ensure Redis is running, ENABLE_MLB_JOBS=true, "
                "and API_SPORTS_KEY is set so background jobs can populate data."
            ),
        )

    return payload


@router.get("/mlb/games/{game_id}", response_model=MlbGameDetailResponse)
async def get_mlb_game_detail(
    game_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Single MLB game — inning box score and season team stats."""
    payload = await build_mlb_game_detail(settings, game_id)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MLB game {game_id} not found.",
        )
    return payload


@router.get("/mlb/sync-status", response_model=MlbSyncStatusResponse)
async def get_mlb_sync_status() -> dict[str, object]:
    """Operational status for MLB background jobs (dev / monitoring)."""
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
