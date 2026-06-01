import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.schemas.insights import HomeInsightsResponse, TeamHomeInsight
from app.services.insights_context import (
    FavoriteTeamContext,
    build_facts_for_favorite,
    pick_primary_favorite,
)
from app.services.insights_store import InsightsStore
from app.services.openai_insights import generate_team_home_insight
from app.types import JsonObject

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


def _insights_store(settings: Settings) -> InsightsStore:
    return InsightsStore(settings)


def _insight_from_payload(payload: JsonObject) -> TeamHomeInsight:
    return TeamHomeInsight.model_validate(payload)


def _response_from_snapshot(snapshot: JsonObject) -> HomeInsightsResponse:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict) or "insight" not in payload:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cached insight snapshot is malformed.",
        )

    insight = _insight_from_payload(payload["insight"])
    generated_at = str(snapshot.get("generated_at") or payload.get("generatedAt") or "")
    facts_as_of = snapshot.get("facts_as_of")
    if facts_as_of is not None:
        facts_as_of = str(facts_as_of)

    return HomeInsightsResponse(
        status="ok",
        generatedAt=generated_at,
        factsAsOf=facts_as_of,
        source="cache",
        insight=insight,
    )


@router.get("/home", response_model=HomeInsightsResponse)
async def get_home_insights(
    user_id: str = Query(..., min_length=1),
    settings: Settings = Depends(get_settings),
) -> HomeInsightsResponse:
    """Latest cached home insight for a user (Supabase snapshot)."""
    store = _insights_store(settings)
    if not store.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase is not configured on the API.",
        )

    snapshot = await store.load_latest_snapshot(user_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No home insights yet. POST /insights/home/generate first.",
        )

    return _response_from_snapshot(snapshot)


@router.post("/home/generate", response_model=HomeInsightsResponse)
async def generate_home_insights(
    user_id: str = Query(..., min_length=1),
    settings: Settings = Depends(get_settings),
) -> HomeInsightsResponse:
    """Generate fresh AI home insights for the user's primary favorite team (NHL/MLB)."""
    if not settings.openai_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI is not configured. Set OPENAI_API_KEY in the API .env.",
        )

    store = _insights_store(settings)
    if not store.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase is not configured on the API.",
        )

    rows = await store.load_favorite_teams(user_id)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No favorite teams found for this user.",
        )

    favorites: list[FavoriteTeamContext] = []
    for row in rows:
        try:
            favorites.append(FavoriteTeamContext(row))
        except ValueError:
            logger.warning("Skipping malformed favorite row for user %s", user_id)

    primary = pick_primary_favorite(favorites)
    if not primary:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Home insights support NHL and MLB favorites only (for now).",
        )

    facts = await build_facts_for_favorite(settings, primary)
    if not facts.get("nextGame") and not facts.get("recentGames"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No {primary.league.upper()} schedule data in cache for {primary.name}. "
                "Ensure Redis jobs are running."
            ),
        )

    try:
        insight = await generate_team_home_insight(
            settings,
            facts,
            team_key=primary.team_key,
            league=primary.league,
            team_name=primary.name,
        )
    except Exception as exc:
        logger.exception("OpenAI home insight generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI generation failed: {exc}",
        ) from exc

    generated_at = datetime.now(timezone.utc).isoformat()
    facts_as_of = str(facts.get("asOf") or generated_at)
    payload: JsonObject = {
        "generatedAt": generated_at,
        "factsAsOf": facts_as_of,
        "insight": insight.model_dump(),
    }

    await store.save_snapshot(
        user_id,
        payload,
        run_type="manual",
        facts_as_of=facts_as_of,
    )

    return HomeInsightsResponse(
        status="ok",
        generatedAt=generated_at,
        factsAsOf=facts_as_of,
        source="openai",
        insight=insight,
    )
