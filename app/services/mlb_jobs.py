"""
Background MLB sync jobs.

API-Sports quota is spent ONLY here — never on user HTTP requests.
"""

import logging
from datetime import datetime, timedelta, timezone
from time import monotonic

from app.config import Settings
from app.services.api_sports import ApiSportsClient
from app.services.mlb import (
    MLB_LEAGUE_ID,
    _LIVE,
    fetch_games_for_date,
    fetch_mlb_games_window,
    fetch_mlb_league,
    get_current_season,
    parse_standings_by_team,
)
from app.services.mlb_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    KEY_SYNC_STATUS,
    build_scores_payload_from_cache,
    records_key,
)
from app.services.redis_store import (
    mlb_sync_lock,
    redis_hmset_json,
    redis_replace_hash_json,
    redis_set_json,
    safe_redis_get_json,
)
from app.types import JsonObject

logger = logging.getLogger(__name__)

MLB_SYNC_LOCK_KEY = "global"
_LOCK_TTL_GLOBAL = 15 * 60
_LOCK_TTL_INITIAL = 15 * 60

_last_window_refresh: float = 0.0


def _is_live(raw: JsonObject) -> bool:
    return raw.get("status", {}).get("short", "") in _LIVE


async def sync_mlb_standings(settings: Settings) -> None:
    async with mlb_sync_lock(MLB_SYNC_LOCK_KEY, _LOCK_TTL_GLOBAL) as acquired:
        if not acquired:
            return
        await _sync_mlb_standings(settings)


async def _sync_mlb_standings(settings: Settings) -> None:
    client = ApiSportsClient(settings)

    league = await fetch_mlb_league(client)
    season = get_current_season(league)

    standings_payload = await client.get_baseball(
        "standings",
        {"league": MLB_LEAGUE_ID, "season": season},
    )
    standings_by_team = parse_standings_by_team(standings_payload)

    await redis_set_json(
        KEY_LEAGUE_META,
        {
            "season": season,
            "league": {
                "id": league.get("id"),
                "name": league.get("name"),
                "logo": league.get("logo"),
                "season": season,
            },
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    await redis_set_json(
        records_key(season),
        {str(team_id): info for team_id, info in standings_by_team.items()},
    )

    status = await redis_get_sync_status()
    status["lastStandingsSync"] = datetime.now(timezone.utc).isoformat()
    status["standingsApiCalls"] = status.get("standingsApiCalls", 0) + 2
    await redis_set_json(KEY_SYNC_STATUS, status)
    logger.info(
        "MLB standings sync complete (season=%s, teams=%s)",
        season,
        len(standings_by_team),
    )


async def sync_mlb_games_window(settings: Settings) -> None:
    async with mlb_sync_lock(MLB_SYNC_LOCK_KEY, _LOCK_TTL_GLOBAL) as acquired:
        if not acquired:
            return
        await _sync_mlb_games_window(settings)


async def _sync_mlb_games_window(settings: Settings) -> None:
    global _last_window_refresh

    client = ApiSportsClient(settings)
    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        await _sync_mlb_standings(settings)
        league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        logger.warning("Skipping MLB window sync — no league metadata")
        return

    season = int(league_meta["season"])
    center = datetime.now(timezone.utc).date()

    raw_games = await fetch_mlb_games_window(
        client,
        season=season,
        center=center,
        lookback_days=settings.mlb_window_lookback_days,
        lookahead_days=settings.mlb_window_lookahead_days,
    )

    mapping = {str(g["id"]): g for g in raw_games if g.get("id") is not None}
    await redis_replace_hash_json(KEY_RAW_GAMES_HASH, mapping)

    _last_window_refresh = monotonic()
    status = await redis_get_sync_status()
    status["lastWindowSync"] = datetime.now(timezone.utc).isoformat()
    status["windowApiCalls"] = status.get("windowApiCalls", 0) + (
        settings.mlb_window_lookback_days + settings.mlb_window_lookahead_days + 1
    )
    await redis_set_json(KEY_SYNC_STATUS, status)
    logger.info("MLB window sync complete (%s games)", len(mapping))


async def sync_mlb_scores_minute(settings: Settings) -> None:
    async with mlb_sync_lock(MLB_SYNC_LOCK_KEY, _LOCK_TTL_GLOBAL) as acquired:
        if not acquired:
            return
        await _sync_mlb_scores_minute(settings)


async def _sync_mlb_scores_minute(settings: Settings) -> None:
    global _last_window_refresh

    client = ApiSportsClient(settings)

    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        await _sync_mlb_standings(settings)
        league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        logger.warning("Skipping MLB minute scores sync — no league metadata")
        return

    season = int(league_meta["season"])

    refresh_interval = settings.mlb_window_refresh_hours * 3600
    if monotonic() - _last_window_refresh >= refresh_interval:
        await _sync_mlb_games_window(settings)

    today = datetime.now(timezone.utc).date()
    dates_to_poll = [today, today - timedelta(days=1)]
    api_calls = 0
    updated: dict[str, JsonObject] = {}

    for game_date in dates_to_poll:
        batch = await fetch_games_for_date(client, season, game_date)
        api_calls += 1
        for game in batch:
            game_id = game.get("id")
            if game_id is not None:
                updated[str(game_id)] = game

    if updated:
        await redis_hmset_json(KEY_RAW_GAMES_HASH, updated)

    live_ids = [gid for gid, g in updated.items() if _is_live(g)]
    payload = await build_scores_payload_from_cache(settings)

    status = await redis_get_sync_status()
    status["lastScoresSync"] = datetime.now(timezone.utc).isoformat()
    status["minuteApiCalls"] = status.get("minuteApiCalls", 0) + api_calls
    status["liveGamesPolled"] = len(live_ids)
    await redis_set_json(KEY_SYNC_STATUS, status)
    logger.info(
        "MLB minute sync: %s day-calls, %s live games, %s games in payload",
        api_calls,
        len(live_ids),
        len(payload.get("games", [])) if payload else 0,
    )


async def redis_get_sync_status() -> JsonObject:
    status = await safe_redis_get_json(KEY_SYNC_STATUS)
    return status if isinstance(status, dict) else {}
