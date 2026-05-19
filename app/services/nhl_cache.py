"""Redis keys and read helpers for NHL data served to clients."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import Settings
from app.services.nhl import map_game
from app.services.redis_store import redis_get_json, redis_hgetall_json, safe_redis_get_json

KEY_LEAGUE_META = "nhl:league:meta"
KEY_RECORDS_PREFIX = "nhl:records:"
KEY_RAW_GAMES_HASH = "nhl:raw_games"
KEY_SCORES_PAYLOAD = "nhl:scores:payload"
KEY_GAME_STATS_PREFIX = "nhl:game_stats:"
KEY_SYNC_STATUS = "nhl:sync:status"

_STATUS_SORT_ORDER = {"live": 0, "scheduled": 1, "final": 2}


def _scheduled_timestamp(game: dict[str, Any]) -> float:
    raw = game.get("scheduledAt")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sort_scoreboard_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live games first, then upcoming, then finals."""

    def sort_key(game: dict[str, Any]) -> tuple[int, float]:
        status = str(game.get("status", "final"))
        priority = _STATUS_SORT_ORDER.get(status, 3)
        timestamp = _scheduled_timestamp(game)
        if status == "scheduled":
            return priority, timestamp
        return priority, -timestamp

    return sorted(games, key=sort_key)


def records_key(season: int) -> str:
    return f"{KEY_RECORDS_PREFIX}{season}"


def game_stats_key(game_id: int | str) -> str:
    return f"{KEY_GAME_STATS_PREFIX}{game_id}"


def _parse_game_date(raw_game: dict[str, Any]) -> date | None:
    raw = raw_game.get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def filter_games_in_window(
    raw_games: list[dict[str, Any]],
    center: date,
    *,
    lookback_days: int,
    lookahead_days: int,
) -> list[dict[str, Any]]:
    start = center - timedelta(days=lookback_days)
    end = center + timedelta(days=lookahead_days)

    in_window: list[dict[str, Any]] = []
    for game in raw_games:
        game_date = _parse_game_date(game)
        if game_date is None:
            continue
        if start <= game_date <= end:
            in_window.append(game)

    return sorted(
        in_window,
        key=lambda g: g.get("timestamp") or 0,
        reverse=True,
    )


async def load_records(season: int) -> dict[int, str]:
    records = await redis_get_json(records_key(season))
    if not isinstance(records, dict):
        return {}
    return {int(k): str(v) for k, v in records.items()}


async def build_scores_payload_from_cache(
    settings: Settings,
    *,
    center: date | None = None,
) -> dict[str, Any] | None:
    """Assemble the mobile scores payload from Redis only (no API-Sports)."""
    # Always map from raw games so live timer/period labels stay current (never
    # return a stale pre-mapped KEY_SCORES_PAYLOAD snapshot).
    center_date = center or datetime.now(timezone.utc).date()
    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        return None

    season = int(league_meta["season"])
    records = await load_records(season)
    try:
        raw_by_id = await redis_hgetall_json(KEY_RAW_GAMES_HASH)
    except RuntimeError:
        return None
    raw_games = list(raw_by_id.values())

    window_games = filter_games_in_window(
        raw_games,
        center_date,
        lookback_days=settings.nhl_window_lookback_days,
        lookahead_days=settings.nhl_window_lookahead_days,
    )
    games = sort_scoreboard_games([map_game(g, records) for g in window_games])

    # Attach stats when present in Redis (optional enrichment).
    for game in games:
        stats = await safe_redis_get_json(game_stats_key(game["id"]))
        if stats is not None:
            game["stats"] = stats

    return {
        "status": "ok",
        "source": "cache",
        "league": league_meta.get("league"),
        "date": center_date.isoformat(),
        "message": f"Serving {len(games)} NHL games from cache.",
        "games": games,
        "sync": await safe_redis_get_json(KEY_SYNC_STATUS),
    }
