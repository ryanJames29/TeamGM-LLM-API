"""Build NHL game detail payloads from Redis + on-demand API-Sports (cached)."""

import logging

from app.config import Settings
from app.services.api_sports import ApiSportsClient
from app.services.nhl import _LIVE, NHL_LEAGUE_ID, map_game
from app.services.nhl_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    load_team_standings,
)
from app.services.redis_store import (
    redis_hget_json,
    redis_hmset_json,
    redis_set_json,
    safe_redis_get_json,
)
from app.types import JsonObject, JsonValue

logger = logging.getLogger(__name__)

TEAM_STATS_PREFIX = "nhl:team_stats:"
GAME_EVENTS_PREFIX = "nhl:game_events:"


def team_stats_key(season: int, team_id: int) -> str:
    return f"{TEAM_STATS_PREFIX}{season}:{team_id}"


def game_events_key(game_id: str) -> str:
    return f"{GAME_EVENTS_PREFIX}{game_id}"


def build_nhl_box_score(raw: JsonObject) -> JsonObject:
    periods = raw.get("periods") if isinstance(raw.get("periods"), dict) else {}
    scores = raw.get("scores") or {}

    rows: list[JsonObject] = []
    for key, label in (
        ("first", "1st"),
        ("second", "2nd"),
        ("third", "3rd"),
        ("overtime", "OT"),
        ("penalties", "SO"),
    ):
        value = periods.get(key)
        if value is None:
            continue
        if isinstance(value, str) and "-" in value:
            # Period lines are home-away; totals in scores.away / scores.home are away-home.
            home_part, away_part = value.split("-", 1)
            rows.append({"label": label, "away": int(away_part), "home": int(home_part)})
        else:
            rows.append({"label": label, "away": None, "home": None})

    return {
        "periods": rows,
        "away": {"goals": scores.get("away")},
        "home": {"goals": scores.get("home")},
    }


def _summarize_team_stats(raw: JsonObject) -> JsonObject:
    games = raw.get("games") or {}
    points = raw.get("points") or {}
    wins = (games.get("wins") or {}).get("all") or {}
    losses = (games.get("loses") or {}).get("all") or {}
    played = (games.get("played") or {}).get("all")

    return {
        "played": played,
        "wins": wins.get("total"),
        "losses": losses.get("total"),
        "winPct": wins.get("percentage"),
        "goalsFor": points.get("for"),
        "goalsAgainst": points.get("against"),
    }


def _map_events(rows: list[JsonValue]) -> list[JsonObject]:
    mapped: list[JsonObject] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        team = row.get("team") if isinstance(row.get("team"), dict) else {}
        mapped.append(
            {
                "period": row.get("period"),
                "minute": row.get("minute"),
                "type": row.get("type"),
                "comment": row.get("comment"),
                "teamName": team.get("name"),
                "players": row.get("players") or [],
                "assists": row.get("assists") or [],
            }
        )
    return mapped


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
        payload = await client.get_hockey(
            "teams/statistics",
            {"league": NHL_LEAGUE_ID, "season": season, "team": team_id},
        )
        response = payload.get("response")
        if not isinstance(response, dict):
            return None
        summary = _summarize_team_stats(response)
        await redis_set_json(team_stats_key(season, team_id), summary, ttl_seconds=3600)
        return summary
    except Exception:
        logger.exception("Failed to fetch NHL team stats team=%s season=%s", team_id, season)
        return None


def _is_live_raw(raw: JsonObject) -> bool:
    short = (raw.get("status") or {}).get("short", "")
    return short in _LIVE


async def _load_game_events(
    client: ApiSportsClient,
    game_id: str,
    *,
    force_refresh: bool = False,
) -> list[JsonObject]:
    if not force_refresh:
        cached = await safe_redis_get_json(game_events_key(game_id))
        if isinstance(cached, list):
            return cached

    try:
        payload = await client.get_hockey("games/events", {"game": game_id})
        rows = payload.get("response") or []
        mapped = _map_events(rows)
        ttl = 300 if mapped else 60
        await redis_set_json(game_events_key(game_id), mapped, ttl_seconds=ttl)
        return mapped
    except Exception:
        logger.exception("Failed to fetch NHL events game=%s", game_id)
        return []


async def _fetch_raw_game_from_api(
    settings: Settings,
    game_id: str,
) -> JsonObject | None:
    client = ApiSportsClient(settings)
    try:
        payload = await client.get_hockey("games", {"id": game_id})
        rows = payload.get("response") or []
        if rows and isinstance(rows[0], dict):
            return rows[0]
    except Exception:
        logger.exception("Failed to fetch NHL game id=%s", game_id)
    return None


async def _load_raw_game(settings: Settings, game_id: str) -> JsonObject | None:
    cached = await redis_hget_json(KEY_RAW_GAMES_HASH, game_id)
    cached_dict = cached if isinstance(cached, dict) else None

    # Live games: always hit API-Sports so period/clock are current (Redis may lag).
    if cached_dict and _is_live_raw(cached_dict):
        fresh = await _fetch_raw_game_from_api(settings, game_id)
        if fresh:
            await redis_hmset_json(KEY_RAW_GAMES_HASH, {game_id: fresh})
            return fresh
        return cached_dict

    if cached_dict:
        return cached_dict

    return await _fetch_raw_game_from_api(settings, game_id)


async def build_nhl_game_detail(settings: Settings, game_id: str) -> JsonObject | None:
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

    events = await _load_game_events(
        client,
        game_id,
        force_refresh=_is_live_raw(raw),
    )

    source = "live" if _is_live_raw(raw) else "cache"

    return {
        "status": "ok",
        "source": source,
        "game": game,
        "boxScore": build_nhl_box_score(raw),
        "teamStats": {"away": away_stats, "home": home_stats},
        "events": events,
        "playerStatsAvailable": False,
        "message": "Player box scores are not provided by the hockey API; scoring events are shown instead.",
    }
