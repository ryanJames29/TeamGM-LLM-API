"""Build MLB game detail payloads from Redis + on-demand API-Sports (cached)."""

import logging

from app.config import Settings
from app.services.api_sports import ApiSportsClient
from app.services.mlb import MLB_LEAGUE_ID, map_game
from app.services.mlb_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    load_team_standings,
)
from app.services.redis_store import (
    redis_hget_json,
    redis_set_json,
    safe_redis_get_json,
)
from app.types import JsonObject, JsonValue

logger = logging.getLogger(__name__)

TEAM_STATS_PREFIX = "mlb:team_stats:"


def team_stats_key(season: int, team_id: int) -> str:
    return f"{TEAM_STATS_PREFIX}{season}:{team_id}"


def build_mlb_box_score(raw: JsonObject) -> JsonObject:
    scores = raw.get("scores") or {}
    away = scores.get("away") if isinstance(scores.get("away"), dict) else {}
    home = scores.get("home") if isinstance(scores.get("home"), dict) else {}

    inning_keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "extra"]
    innings: list[JsonObject] = []
    for key in inning_keys:
        away_runs = away.get("innings", {}).get(key) if isinstance(away.get("innings"), dict) else None
        home_runs = home.get("innings", {}).get(key) if isinstance(home.get("innings"), dict) else None
        if away_runs is None and home_runs is None and key == "extra":
            continue
        innings.append(
            {
                "label": "Extra" if key == "extra" else key,
                "away": away_runs,
                "home": home_runs,
            }
        )

    return {
        "innings": innings,
        "away": {
            "runs": away.get("total"),
            "hits": away.get("hits"),
            "errors": away.get("errors"),
        },
        "home": {
            "runs": home.get("total"),
            "hits": home.get("hits"),
            "errors": home.get("errors"),
        },
    }


def _summarize_team_stats(raw: JsonObject) -> JsonObject:
    games = raw.get("games") or {}
    points = raw.get("points") or {}
    wins = (games.get("wins") or {}).get("all") or {}
    losses = (games.get("loses") or {}).get("all") or {}
    played = (games.get("played") or {}).get("all")
    scored = (points.get("for") or {}).get("total") or {}
    allowed = (points.get("against") or {}).get("total") or {}

    return {
        "played": played,
        "wins": wins.get("total"),
        "losses": losses.get("total"),
        "winPct": wins.get("percentage"),
        "runsFor": scored.get("all") if isinstance(scored, dict) else scored,
        "runsAgainst": allowed.get("all") if isinstance(allowed, dict) else allowed,
    }


async def _load_team_stats(
    client: ApiSportsClient,
    *,
    season: int,
    team_id: int,
) -> JsonObject | None:
    cached = await safe_redis_get_json(team_stats_key(season, team_id))
    if isinstance(cached, dict):
        return cached

    try:
        payload = await client.get_baseball(
            "teams/statistics",
            {"league": MLB_LEAGUE_ID, "season": season, "team": team_id},
        )
        response = payload.get("response")
        if not isinstance(response, dict):
            return None
        summary = _summarize_team_stats(response)
        await redis_set_json(team_stats_key(season, team_id), summary, ttl_seconds=3600)
        return summary
    except Exception:
        logger.exception("Failed to fetch MLB team stats team=%s season=%s", team_id, season)
        return None


async def _load_raw_game(settings: Settings, game_id: str) -> JsonObject | None:
    raw = await redis_hget_json(KEY_RAW_GAMES_HASH, game_id)
    if isinstance(raw, dict):
        return raw

    client = ApiSportsClient(settings)
    try:
        payload = await client.get_baseball("games", {"id": game_id})
        rows = payload.get("response") or []
        if rows and isinstance(rows[0], dict):
            return rows[0]
    except Exception:
        logger.exception("Failed to fetch MLB game id=%s", game_id)
    return None


async def build_mlb_game_detail(settings: Settings, game_id: str) -> JsonObject | None:
    raw = await _load_raw_game(settings, game_id)
    if not raw:
        return None

    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    season = int((league_meta or {}).get("season") or raw.get("league", {}).get("season") or 0)
    if not season:
        return None

    standings = await load_team_standings(season)
    game = map_game(raw, standings)
    client = ApiSportsClient(settings)

    away_id = raw.get("teams", {}).get("away", {}).get("id")
    home_id = raw.get("teams", {}).get("home", {}).get("id")
    away_stats = None
    home_stats = None
    if away_id is not None:
        away_stats = await _load_team_stats(client, season=season, team_id=int(away_id))
    if home_id is not None:
        home_stats = await _load_team_stats(client, season=season, team_id=int(home_id))

    return {
        "status": "ok",
        "source": "cache",
        "game": game,
        "boxScore": build_mlb_box_score(raw),
        "teamStats": {"away": away_stats, "home": home_stats},
        "events": [],
        "playerStatsAvailable": False,
        "message": "Player-level stats are not provided by the baseball API plan.",
    }
