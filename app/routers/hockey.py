import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.services.api_sports import ApiSportsClient
from app.services.nhl import build_nhl_scores_payload, fetch_nhl_league, get_current_season

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hockey", tags=["hockey"])


def get_api_sports_client(
    settings: Settings = Depends(get_settings),
) -> ApiSportsClient:
    return ApiSportsClient(settings)


@router.get("/leagues")
async def list_leagues(
    client: ApiSportsClient = Depends(get_api_sports_client),
) -> dict[str, Any]:
    """Proxy to API-Sports GET /leagues (validates API_SPORTS_KEY)."""
    logger.info("Hockey leagues — request received from client")
    payload = await client.get_hockey("leagues")
    response_list = payload.get("response") or []
    return {
        "status": "ok",
        "message": f"Fetched {len(response_list)} hockey leagues from API-Sports.",
        "results": payload.get("results"),
        "leagues": response_list,
    }


@router.get("/nhl/league")
async def get_nhl_league(
    client: ApiSportsClient = Depends(get_api_sports_client),
) -> dict[str, Any]:
    """NHL league metadata (API-Sports league id 57)."""
    logger.info("NHL league — request received from client")
    try:
        league = await fetch_nhl_league(client)
        season = get_current_season(league)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return {
        "status": "ok",
        "league": {
            "id": league.get("id"),
            "name": league.get("name"),
            "logo": league.get("logo"),
            "country": league.get("country"),
            "season": season,
            "seasons": league.get("seasons"),
        },
    }


@router.get("/nhl/games")
async def get_nhl_games(
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="Center date (YYYY-MM-DD). Defaults to today (UTC).",
    ),
    client: ApiSportsClient = Depends(get_api_sports_client),
) -> dict[str, Any]:
    """NHL games for a date window with scores mapped for the mobile app."""
    logger.info("NHL games — request received from client")
    game_date: date | None = None
    if date_param is not None:
        try:
            game_date = date.fromisoformat(date_param)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date must be YYYY-MM-DD",
            ) from exc

    try:
        return await build_nhl_scores_payload(client, game_date=game_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
