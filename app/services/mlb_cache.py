"""Redis keys and read helpers for MLB data served to clients."""

from datetime import date, datetime, timedelta, timezone

from app.config import Settings
from app.services.mlb import TeamStanding, _LIVE, _SCHEDULED, map_game
from app.services.redis_store import (
    redis_get_json,
    safe_redis_get_json,
    safe_redis_hgetall_json,
)
from app.types import JsonObject, JsonValue

KEY_LEAGUE_META = "mlb:league:meta"
KEY_RECORDS_PREFIX = "mlb:records:"
KEY_RAW_GAMES_HASH = "mlb:raw_games"
KEY_GAME_STATS_PREFIX = "mlb:game_stats:"
KEY_SYNC_STATUS = "mlb:sync:status"

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


def _parse_game_date(raw_game: JsonObject, *, tz_offset_minutes: int = 0) -> date | None:
    raw = raw_game.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        local = dt + timedelta(minutes=tz_offset_minutes)
        return local.date()
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


def _is_yesterday_or_today_live(
    raw_game: JsonObject,
    today: date,
    *,
    tz_offset_minutes: int = 0,
) -> bool:
    game_date = _parse_game_date(raw_game, tz_offset_minutes=tz_offset_minutes)
    if game_date is None:
        return False
    yesterday = today - timedelta(days=1)
    return yesterday <= game_date <= today


def filter_games_for_scoreboard(
    raw_games: list[JsonObject],
    *,
    today: date,
    tz_offset_minutes: int = 0,
) -> list[JsonObject]:
    tomorrow = today + timedelta(days=1)
    playing_today: set[int] = set()
    today_games: list[JsonObject] = []

    for game in raw_games:
        if _is_live_raw(game) and _is_yesterday_or_today_live(
            game,
            today,
            tz_offset_minutes=tz_offset_minutes,
        ):
            today_games.append(game)
            playing_today |= _team_ids(game)
            continue

        if _parse_game_date(game, tz_offset_minutes=tz_offset_minutes) == today:
            today_games.append(game)
            playing_today |= _team_ids(game)

    today_ids = {game.get("id") for game in today_games}
    tomorrow_rest: list[JsonObject] = []

    for game in raw_games:
        if game.get("id") in today_ids:
            continue
        if (
            _parse_game_date(game, tz_offset_minutes=tz_offset_minutes) != tomorrow
            or not _is_scheduled_raw(game)
        ):
            continue
        team_ids = _team_ids(game)
        if team_ids and team_ids.isdisjoint(playing_today):
            tomorrow_rest.append(game)

    return today_games + tomorrow_rest


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
    tz_offset_minutes: int = 0,
) -> JsonObject | None:
    now_local = datetime.now(timezone.utc) + timedelta(minutes=tz_offset_minutes)
    center_date = center or now_local.date()
    league_meta = await safe_redis_get_json(KEY_LEAGUE_META)
    if not league_meta:
        return None

    season = int(league_meta["season"])
    standings = await load_team_standings(season)
    raw_by_id = await safe_redis_hgetall_json(KEY_RAW_GAMES_HASH)
    if raw_by_id is None:
        return None
    raw_games = list(raw_by_id.values())

    scoreboard_raw = filter_games_for_scoreboard(
        raw_games,
        today=center_date,
        tz_offset_minutes=tz_offset_minutes,
    )
    games = sort_scoreboard_games([map_game(g, standings) for g in scoreboard_raw])

    for game in games:
        stats = await safe_redis_get_json(game_stats_key(game["id"]))
        if stats is not None:
            game["stats"] = stats

    return {
        "status": "ok",
        "source": "cache",
        "league": league_meta.get("league"),
        "date": center_date.isoformat(),
        "message": f"Serving {len(games)} MLB games from cache.",
        "games": games,
        "sync": await safe_redis_get_json(KEY_SYNC_STATUS),
    }
