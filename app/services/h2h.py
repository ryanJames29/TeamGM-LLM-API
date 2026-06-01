import logging

from app.config import Settings
from app.services.api_sports import ApiSportsClient
from app.services.mlb import MLB_LEAGUE_ID
from app.services.nhl import NHL_LEAGUE_ID
from app.types import JsonObject

logger = logging.getLogger(__name__)

MAX_H2H_GAMES = 10


def _side_score(scores: JsonObject, side: str, *, league: str) -> int | None:
    raw = scores.get(side)
    if league == "mlb":
        if isinstance(raw, dict):
            total = raw.get("total")
            return int(total) if total is not None else None
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, dict):
        total = raw.get("total")
        return int(total) if total is not None else None
    return None


def _summarize_h2h_game(raw: JsonObject, focal_team_id: int, *, league: str) -> JsonObject:
    home = (raw.get("teams") or {}).get("home") or {}
    away = (raw.get("teams") or {}).get("away") or {}
    home_id = home.get("id")
    is_home = home_id == focal_team_id
    focal_side = "home" if is_home else "away"
    opp_side = "away" if is_home else "home"
    scores = raw.get("scores") or {}
    focal_score = _side_score(scores, focal_side, league=league)
    opp_score = _side_score(scores, opp_side, league=league)

    result = "unknown"
    if focal_score is not None and opp_score is not None:
        if focal_score > opp_score:
            result = "win"
        elif focal_score < opp_score:
            result = "loss"
        else:
            result = "tie"

    return {
        "date": raw.get("date"),
        "focalTeam": (home if is_home else away).get("name"),
        "opponent": (away if is_home else home).get("name"),
        "location": "home" if is_home else "away",
        "focalScore": focal_score,
        "opponentScore": opp_score,
        "result": result,
    }


def _build_h2h_summary(
    games: list[JsonObject],
    *,
    focal_team_id: int,
    opponent_id: int,
    league: str,
) -> JsonObject:
    summaries = [
        _summarize_h2h_game(game, focal_team_id, league=league)
        for game in games[:MAX_H2H_GAMES]
    ]
    wins = sum(1 for game in summaries if game.get("result") == "win")
    losses = sum(1 for game in summaries if game.get("result") == "loss")
    ties = sum(1 for game in summaries if game.get("result") == "tie")

    return {
        "focalTeamId": focal_team_id,
        "opponentTeamId": opponent_id,
        "sampleSize": len(summaries),
        "focalTeamWins": wins,
        "focalTeamLosses": losses,
        "ties": ties,
        "recentMeetings": summaries,
    }


async def load_head_to_head(
    settings: Settings,
    *,
    league: str,
    focal_team_id: int,
    opponent_id: int,
    season: int | None = None,
) -> JsonObject | None:
    if not settings.api_sports_key or not settings.api_sports_key.strip():
        logger.info("Skipping H2H fetch — API_SPORTS_KEY is not configured.")
        return None

    params: dict[str, object] = {"h2h": f"{focal_team_id}-{opponent_id}"}
    if season is not None:
        params["season"] = season

    client = ApiSportsClient(settings)

    try:
        if league == "nhl":
            params["league"] = NHL_LEAGUE_ID
            payload = await client.get_hockey("games/h2h", params)
        elif league == "mlb":
            params["league"] = MLB_LEAGUE_ID
            payload = await client.get_baseball("games/h2h", params)
        else:
            return None
    except Exception:
        logger.exception(
            "H2H fetch failed league=%s teams=%s-%s",
            league,
            focal_team_id,
            opponent_id,
        )
        return None

    response = payload.get("response")
    if not isinstance(response, list) or not response:
        return {
            "focalTeamId": focal_team_id,
            "opponentTeamId": opponent_id,
            "sampleSize": 0,
            "focalTeamWins": 0,
            "focalTeamLosses": 0,
            "ties": 0,
            "recentMeetings": [],
        }

    return _build_h2h_summary(
        response,
        focal_team_id=focal_team_id,
        opponent_id=opponent_id,
        league=league,
    )
