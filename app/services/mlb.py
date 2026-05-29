import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import TypedDict

from app.services.api_sports import ApiSportsClient
from app.types import JsonObject, JsonValue

logger = logging.getLogger(__name__)

MLB_LEAGUE_ID = 1
_SCHEDULED = frozenset({"NS", "TBD"})
_LIVE = frozenset({f"IN{n}" for n in range(1, 10)})
_FINAL = frozenset({"FT"})
_CANCELLED = frozenset({"POST", "CANC", "INTR", "ABD"})

_INNING_SHORT = re.compile(r"^IN(\d+)$")

MLB_TEAM_ABBREVIATIONS: dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Athletics": "ATH",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Cleveland Indians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


class TeamStanding(TypedDict, total=False):
    record: str
    standing: str | None
    position: int | None
    teamName: str | None


def _team_abbreviation(name: str) -> str:
    if name in MLB_TEAM_ABBREVIATIONS:
        return MLB_TEAM_ABBREVIATIONS[name]
    parts = name.split()
    return (parts[-1][:3] if parts else name[:3]).upper()


def _format_record(games: JsonObject) -> str:
    wins = games.get("win", {}).get("total", 0)
    losses = games.get("lose", {}).get("total", 0)
    return f"{wins}-{losses}"


def _map_status(short: str) -> str:
    if short in _SCHEDULED or short == "POST":
        return "scheduled"
    if short in _LIVE:
        return "live"
    if short in _FINAL or short in _CANCELLED:
        return "final"
    logger.warning("Unknown API-Sports status short=%s; treating as scheduled", short)
    return "scheduled"


def _side_score(scores: JsonObject, side: str) -> int | None:
    block = scores.get(side)
    if isinstance(block, dict):
        total = block.get("total")
        return int(total) if total is not None else None
    if isinstance(block, int):
        return block
    return None


def _cancelled_label(status_short: str, status_long: str) -> str:
    if status_short == "POST":
        return "Postponed"
    if status_short == "CANC":
        return "Cancelled"
    if status_short == "ABD":
        return "Abandoned"
    if status_short == "INTR":
        return "Interrupted"
    return status_long or "Cancelled"


def _period_label(status_short: str, status_long: str) -> str | None:
    if status_short in _CANCELLED:
        return _cancelled_label(status_short, status_long)
    if status_short in _FINAL:
        return "Final"
    if status_short in _SCHEDULED:
        return None

    match = _INNING_SHORT.match(status_short)
    if match:
        return status_long or f"Inning {match.group(1)}"

    if status_short in _LIVE:
        return status_long or "Live"

    return status_long or None


def _map_team(
    team: JsonObject,
    score: int | None,
    standings: dict[int, TeamStanding],
    *,
    is_scheduled: bool,
) -> JsonObject:
    team_id = team.get("id")
    name = team.get("name", "Unknown")
    info: TeamStanding = {}
    if team_id is not None:
        raw_info = standings.get(int(team_id), "—")
        if isinstance(raw_info, str):
            info = {"record": raw_info, "standing": None}
        elif isinstance(raw_info, dict):
            info = raw_info

    return {
        "name": name,
        "abbreviation": _team_abbreviation(name),
        "record": info.get("record", "—"),
        "standing": info.get("standing"),
        "score": None if is_scheduled else score,
    }


def map_game(raw: JsonObject, standings: dict[int, TeamStanding]) -> JsonObject:
    status_short = raw.get("status", {}).get("short", "NS")
    status_long = raw.get("status", {}).get("long", "")
    game_status = _map_status(status_short)
    is_scheduled = game_status == "scheduled"

    scores = raw.get("scores") or {}
    away = raw.get("teams", {}).get("away", {})
    home = raw.get("teams", {}).get("home", {})

    return {
        "id": str(raw.get("id")),
        "league": "mlb",
        "status": game_status,
        "periodLabel": _period_label(status_short, status_long),
        "scheduledAt": raw.get("date"),
        "venue": raw.get("week") or "",
        "awayTeam": _map_team(
            away,
            _side_score(scores, "away"),
            standings,
            is_scheduled=is_scheduled,
        ),
        "homeTeam": _map_team(
            home,
            _side_score(scores, "home"),
            standings,
            is_scheduled=is_scheduled,
        ),
    }


def get_current_season(league_payload: JsonObject) -> int:
    seasons = league_payload.get("seasons") or []
    for season in seasons:
        if season.get("current"):
            return int(season["season"])
    if seasons:
        return max(int(s["season"]) for s in seasons)
    raise ValueError("No seasons found for MLB league")


async def fetch_mlb_league(client: ApiSportsClient) -> JsonObject:
    payload = await client.get_baseball("leagues", {"id": MLB_LEAGUE_ID})
    rows = payload.get("response") or []
    if not rows:
        raise ValueError("MLB league not found")
    return rows[0]


def _flatten_standings_response(response: list[JsonValue]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for item in response:
        if isinstance(item, list):
            rows.extend(item)
        elif isinstance(item, dict):
            rows.append(item)
    return rows


def _ordinal(position: int) -> str:
    if 11 <= position % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(position % 10, "th")
    return f"{position}{suffix}"


def _format_standing_label(row: JsonObject) -> str | None:
    position = row.get("position")
    if position is None:
        return None

    group_name = (row.get("group") or {}).get("name", "")
    label = _ordinal(int(position))

    if "division" in group_name.lower():
        short = (
            group_name.replace(" Division", "")
            .replace("AL ", "AL ")
            .replace("NL ", "NL ")
        )
        return f"{label} {short}"

    if group_name in ("American League", "National League"):
        league_short = "AL" if group_name.startswith("American") else "NL"
        return f"{label} {league_short}"

    return label


def _standings_info_from_row(row: JsonObject) -> TeamStanding:
    team = row.get("team") or {}
    games = row.get("games") or {}
    return {
        "record": _format_record(games) if games else "—",
        "standing": _format_standing_label(row),
        "position": row.get("position"),
        "teamName": team.get("name"),
    }


def _pick_standings_row(rows: list[JsonObject]) -> JsonObject | None:
    if not rows:
        return None

    division_rows = [
        row
        for row in rows
        if "division" in str((row.get("group") or {}).get("name", "")).lower()
    ]
    pool = division_rows if division_rows else rows
    return max(pool, key=lambda row: (row.get("games") or {}).get("played", 0))


def parse_standings_by_team(payload: JsonObject) -> dict[int, TeamStanding]:
    rows_by_team: dict[int, list[JsonObject]] = {}
    for row in _flatten_standings_response(payload.get("response") or []):
        team = row.get("team") or {}
        team_id = team.get("id")
        if team_id is not None:
            rows_by_team.setdefault(int(team_id), []).append(row)

    standings: dict[int, TeamStanding] = {}
    for team_id, team_rows in rows_by_team.items():
        best_row = _pick_standings_row(team_rows)
        if best_row is not None:
            standings[team_id] = _standings_info_from_row(best_row)
    return standings


def parse_standings_records(payload: JsonObject) -> dict[int, str]:
    return {
        team_id: info["record"]
        for team_id, info in parse_standings_by_team(payload).items()
    }


async def fetch_games_for_date(
    client: ApiSportsClient,
    season: int,
    game_date: date,
) -> list[JsonObject]:
    payload = await client.get_baseball(
        "games",
        {
            "league": MLB_LEAGUE_ID,
            "season": season,
            "date": game_date.isoformat(),
        },
    )
    return payload.get("response") or []


async def fetch_mlb_games_window(
    client: ApiSportsClient,
    *,
    season: int,
    center: date,
    lookback_days: int = 7,
    lookahead_days: int = 3,
) -> list[JsonObject]:
    start = center - timedelta(days=lookback_days)
    end = center + timedelta(days=lookahead_days)
    dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    batches = await asyncio.gather(
        *[fetch_games_for_date(client, season, d) for d in dates]
    )

    by_id: dict[int, JsonObject] = {}
    for batch in batches:
        for game in batch:
            game_id = game.get("id")
            if game_id is not None:
                by_id[game_id] = game

    return sorted(
        by_id.values(),
        key=lambda g: g.get("timestamp") or 0,
        reverse=True,
    )
