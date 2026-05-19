"""
Background NHL sync jobs.

API-Sports quota is spent ONLY here — never on user HTTP requests.

Schedules (defaults):
  - Standings + league metadata: hourly → Supabase + Redis
  - Scores window backfill: daily → Redis raw games hash
  - Live scores + today/yesterday + game stats: every minute → Redis
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any

from app.config import Settings
from app.services.api_sports import ApiSportsClient
from app.services.nhl import (
    NHL_LEAGUE_ID,
    _LIVE,
    _flatten_standings_response,
    fetch_games_for_date,
    fetch_nhl_games_window,
    fetch_nhl_league,
    get_current_season,
    parse_standings_records,
)
from app.services.nhl_cache import (
    KEY_LEAGUE_META,
    KEY_RAW_GAMES_HASH,
    KEY_SCORES_PAYLOAD,
    KEY_SYNC_STATUS,
    build_scores_payload_from_cache,
    game_stats_key,
    records_key,
)
from app.services.redis_store import redis_hmset_json, redis_set_json
from app.services.supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

_job_lock = asyncio.Lock()
_last_window_refresh: float = 0.0


def _standings_rows(records: dict[int, str], raw_response: list[Any]) -> list[dict[str, Any]]:
    """Flatten API standings into rows for Supabase."""
    rows: list[dict[str, Any]] = []
    for row in _flatten_standings_response(raw_response):
        team = row.get("team") or {}
        team_id = team.get("id")
        if team_id is None:
            continue
        games = row.get("games") or {}
        wins = games.get("win", {}).get("total", 0)
        losses = games.get("lose", {}).get("total", 0)
        otl = games.get("lose_overtime", {}).get("total", 0)
        rows.append(
            {
                "team_id": team_id,
                "team_name": team.get("name", "Unknown"),
                "wins": wins,
                "losses": losses,
                "ot_losses": otl,
                "record": records.get(team_id, f"{wins}-{losses}-{otl}"),
                "points": row.get("points"),
                "position": row.get("position"),
            }
        )
    return rows


def _is_live(raw: dict[str, Any]) -> bool:
    return raw.get("status", {}).get("short", "") in _LIVE


async def _fetch_game_statistics(
    client: ApiSportsClient,
    game_id: int,
) -> dict[str, Any] | None:
    """Hockey v1 has no games/statistics endpoint — skip until API-Sports adds it."""
    del client, game_id
    return None


async def sync_nhl_standings(settings: Settings) -> None:
    """Hourly: league metadata + standings → Supabase + Redis records."""
    client = ApiSportsClient(settings)
    supabase = SupabaseStore(settings)

    league = await fetch_nhl_league(client)
    season = get_current_season(league)

    standings_payload = await client.get_hockey(
        "standings",
        {"league": NHL_LEAGUE_ID, "season": season},
    )
    records = parse_standings_records(standings_payload)

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
    await redis_set_json(records_key(season), {str(k): v for k, v in records.items()})

    if supabase.enabled:
        try:
            rows = _standings_rows(records, standings_payload.get("response") or [])
            await supabase.upsert_team_records(season, rows)
        except Exception:
            logger.exception(
                "Supabase standings upsert failed — Redis cache is still updated; "
                "check SUPABASE_URL (no /rest/v1 suffix) and that nhl_team_records exists"
            )

    status = await redis_get_sync_status()
    status["lastStandingsSync"] = datetime.now(timezone.utc).isoformat()
    status["standingsApiCalls"] = status.get("standingsApiCalls", 0) + 2
    await redis_set_json(KEY_SYNC_STATUS, status)
    logger.info("NHL standings sync complete (season=%s, teams=%s)", season, len(records))


async def sync_nhl_games_window(settings: Settings) -> None:
    """Daily / on startup: backfill 7+3 day window into Redis (11 API calls once)."""
    global _last_window_refresh

    client = ApiSportsClient(settings)
    league_meta = await redis_get_json_safe(KEY_LEAGUE_META)
    if not league_meta:
        await sync_nhl_standings(settings)
        league_meta = await redis_get_json_safe(KEY_LEAGUE_META)
    if not league_meta:
        logger.warning("Skipping window sync — no league metadata")
        return

    season = int(league_meta["season"])
    center = datetime.now(timezone.utc).date()

    raw_games = await fetch_nhl_games_window(
        client,
        season=season,
        center=center,
        lookback_days=settings.nhl_window_lookback_days,
        lookahead_days=settings.nhl_window_lookahead_days,
    )

    mapping = {str(g["id"]): g for g in raw_games if g.get("id") is not None}
    await redis_hmset_json(KEY_RAW_GAMES_HASH, mapping)

    _last_window_refresh = monotonic()
    status = await redis_get_sync_status()
    status["lastWindowSync"] = datetime.now(timezone.utc).isoformat()
    status["windowApiCalls"] = status.get("windowApiCalls", 0) + (
        settings.nhl_window_lookback_days + settings.nhl_window_lookahead_days + 1
    )
    await redis_set_json(KEY_SYNC_STATUS, status)
    logger.info("NHL window sync complete (%s games)", len(mapping))


async def sync_nhl_scores_minute(settings: Settings) -> None:
    """
    Every minute: refresh today + yesterday games, stats for live games, rebuild payload.

    Typical API usage per run: 2 game-day calls + up to N live statistics calls.
    """
    global _last_window_refresh

    async with _job_lock:
        client = ApiSportsClient(settings)
        supabase = SupabaseStore(settings)

        league_meta = await redis_get_json_safe(KEY_LEAGUE_META)
        if not league_meta:
            await sync_nhl_standings(settings)
            league_meta = await redis_get_json_safe(KEY_LEAGUE_META)
        if not league_meta:
            logger.warning("Skipping minute scores sync — no league metadata")
            return

        season = int(league_meta["season"])
        records = await redis_get_json_safe(records_key(season))
        if not isinstance(records, dict) or not records:
            if supabase.enabled:
                db_records = await supabase.load_records_map(season)
                records = {str(k): v for k, v in db_records.items()}
                await redis_set_json(records_key(season), records)
            else:
                records = {}

        # Refresh full window once per day (or on cold start).
        refresh_interval = settings.nhl_window_refresh_hours * 3600
        if monotonic() - _last_window_refresh >= refresh_interval:
            await sync_nhl_games_window(settings)

        today = datetime.now(timezone.utc).date()
        dates_to_poll = [today, today - timedelta(days=1)]
        api_calls = 0
        updated: dict[str, Any] = {}

        for game_date in dates_to_poll:
            batch = await fetch_games_for_date(client, season, game_date)
            api_calls += 1
            for game in batch:
                game_id = game.get("id")
                if game_id is not None:
                    updated[str(game_id)] = game

        if updated:
            await redis_hmset_json(KEY_RAW_GAMES_HASH, updated)

        live_ids = [int(gid) for gid, g in updated.items() if _is_live(g)]
        stats_calls = 0
        for game_id in live_ids[:12]:
            stats = await _fetch_game_statistics(client, game_id)
            stats_calls += 1
            if stats is not None:
                await redis_set_json(game_stats_key(game_id), stats, ttl_seconds=7200)

        payload = await build_scores_payload_from_cache(settings)
        if payload is not None:
            await redis_set_json(KEY_SCORES_PAYLOAD, payload, ttl_seconds=300)

        status = await redis_get_sync_status()
        status["lastScoresSync"] = datetime.now(timezone.utc).isoformat()
        status["minuteApiCalls"] = status.get("minuteApiCalls", 0) + api_calls + stats_calls
        status["liveGamesPolled"] = len(live_ids)
        await redis_set_json(KEY_SYNC_STATUS, status)
        logger.info(
            "NHL minute sync: %s day-calls, %s live stats, %s games in payload",
            api_calls,
            stats_calls,
            len(payload.get("games", [])) if payload else 0,
        )


async def redis_get_json_safe(key: str) -> Any | None:
    from app.services.redis_store import redis_get_json

    try:
        return await redis_get_json(key)
    except RuntimeError:
        return None


async def redis_get_sync_status() -> dict[str, Any]:
    status = await redis_get_json_safe(KEY_SYNC_STATUS)
    return status if isinstance(status, dict) else {}
