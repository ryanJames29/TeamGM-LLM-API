"""Redis keys and read helpers for NHL data served to clients."""

from datetime import date, datetime, timedelta, timezone

from app.config import Settings
from app.services.nhl import TeamStanding, _LIVE, _SCHEDULED, map_game
from app.services.redis_store import (
    redis_get_json,
    safe_redis_get_json,
    safe_redis_hgetall_json,
)
from app.types import JsonObject, JsonValue

KEY_LEAGUE_META = "nhl:league:meta"
KEY_RECORDS_PREFIX = "nhl:records:"
KEY_RAW_GAMES_HASH = "nhl:raw_games"
KEY_GAME_STATS_PREFIX = "nhl:game_stats:"
KEY_SYNC_STATUS = "nhl:sync:status"

_STATUS_SORT_ORDER = {"live": 0, "scheduled": 1, "final": 2}


def _scheduled_timestamp(game: JsonObject) -> float:
    raw = game.get("scheduledAt")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def sort_scoreboard_games(games: list[JsonObject]) -> list[JsonObject]:
    """Live games first, then upcoming, then finals."""

    def sort_key(game: JsonObject) -> tuple[int, float]:
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


def _parse_game_date(raw_game: JsonObject) -> date | None:
    raw = raw_game.get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_live_raw(raw_game: JsonObject) -> bool:
    short = (raw_game.get("status") or {}).get("short", "")
    return short in _LIVE


def _team_ids(raw_game: JsonObject) -> set[int]:
    teams = raw_game.get("teams") or {}
    ids: set[int] = set()
    for side in ("home", "away"):
        team_id = (teams.get(side) or {}).get("id")
        if team_id is not None:
            ids.add(int(team_id))
    return ids


def _is_scheduled_raw(raw_game: JsonObject) -> bool:
    short = (raw_game.get("status") or {}).get("short", "")
    return short in _SCHEDULED


def _is_yesterday_or_today_live(raw_game: JsonObject, today: date) -> bool:
    """Only trust live status for games from yesterday or today (handles midnight spillover)."""
    game_date = _parse_game_date(raw_game)
    if game_date is None:
        return False
    yesterday = today - timedelta(days=1)
    return yesterday <= game_date <= today


def filter_games_for_scoreboard(
    raw_games: list[JsonObject],
    *,
    today: date,
) -> list[JsonObject]:
    """
    Scoreboard view (UTC):
      1. All of today's games (live, final, scheduled) plus any still-live from earlier.
      2. Tomorrow's scheduled games where neither team plays today.

    The 7+3 day window stays in Redis for other features; this only shapes the list.
    """
    tomorrow = today + timedelta(days=1)
    playing_today: set[int] = set()
    today_games: list[JsonObject] = []

    for game in raw_games:
        if _is_live_raw(game) and _is_yesterday_or_today_live(game, today):
            today_games.append(game)
            playing_today |= _team_ids(game)
            continue

        if _parse_game_date(game) == today:
            today_games.append(game)
            playing_today |= _team_ids(game)

    today_ids = {game.get("id") for game in today_games}
    tomorrow_rest: list[JsonObject] = []

    for game in raw_games:
        if game.get("id") in today_ids:
            continue
        if _parse_game_date(game) != tomorrow or not _is_scheduled_raw(game):
            continue
        team_ids = _team_ids(game)
        if team_ids and team_ids.isdisjoint(playing_today):
            tomorrow_rest.append(game)

    return today_games + tomorrow_rest


def filter_games_in_window(
    raw_games: list[JsonObject],
    center: date,
    *,
    lookback_days: int,
    lookahead_days: int,
) -> list[JsonObject]:
    start = center - timedelta(days=lookback_days)
    end = center + timedelta(days=lookahead_days)

    in_window: list[JsonObject] = []
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


async def load_team_standings(season: int) -> dict[int, TeamStanding]:
    raw = await redis_get_json(records_key(season))
    if not isinstance(raw, dict):
        return {}

    standings: dict[int, TeamStanding] = {}
    for key, value in raw.items():
        team_id = int(key)
        if isinstance(value, str):
            standings[team_id] = {"record": value, "standing": None}
        elif isinstance(value, dict):
            standings[team_id] = value
    return standings


async def build_scores_payload_from_cache(
    settings: Settings,
    *,
    center: date | None = None,
) -> JsonObject | None:
    """Assemble the mobile scores payload from Redis only (no API-Sports)."""
    center_date = center or datetime.now(timezone.utc).date()
    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        return None

    season = int(league_meta["season"])
    standings = await load_team_standings(season)
    raw_by_id = await safe_redis_hgetall_json(KEY_RAW_GAMES_HASH)
    if raw_by_id is None:
        return None
    raw_games = list(raw_by_id.values())

    scoreboard_raw = filter_games_for_scoreboard(raw_games, today=center_date)
    games = sort_scoreboard_games([map_game(g, standings) for g in scoreboard_raw])

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
