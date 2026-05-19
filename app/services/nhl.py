import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.api_sports import ApiSportsClient

logger = logging.getLogger(__name__)

NHL_LEAGUE_ID = 57
# API-Sports status.short values
_SCHEDULED = frozenset({"NS", "TBD"})
_LIVE = frozenset({"P1", "P2", "P3", "OT", "PT", "BT", "LIVE"})
_FINAL = frozenset({"FT", "AP", "AOT", "PEN", "AW", "WO"})
_CANCELLED = frozenset({"CANC", "ABD"})

NHL_TEAM_ABBREVIATIONS: dict[str, str] = {
    "Anaheim Ducks": "ANA",
    "Arizona Coyotes": "ARI",
    "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY",
    "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ",
    "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM",
    "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN",
    "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH",
    "New Jersey Devils": "NJD",
    "New York Islanders": "NYI",
    "New York Rangers": "NYR",
    "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA",
    "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR",
    "Utah Hockey Club": "UTA",
    "Vancouver Canucks": "VAN",
    "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH",
    "Winnipeg Jets": "WPG",
}


def _team_abbreviation(name: str) -> str:
    if name in NHL_TEAM_ABBREVIATIONS:
        return NHL_TEAM_ABBREVIATIONS[name]
    parts = name.split()
    return (parts[-1][:3] if parts else name[:3]).upper()


def _format_record(games: dict[str, Any]) -> str:
    wins = games.get("win", {}).get("total", 0)
    losses = games.get("lose", {}).get("total", 0)
    otl = games.get("lose_overtime", {}).get("total", 0)
    return f"{wins}-{losses}-{otl}"


def _map_status(short: str) -> str:
    if short in _SCHEDULED:
        return "scheduled"
    if short in _LIVE:
        return "live"
    if short in _FINAL or short in _CANCELLED:
        return "final"
    logger.warning("Unknown API-Sports status short=%s; treating as scheduled", short)
    return "scheduled"


_PERIOD_ABBREV: dict[str, str] = {
    "P1": "1st",
    "P2": "2nd",
    "P3": "3rd",
    "OT": "OT",
    "PT": "OT",
    "SO": "SO",
}

# API-Sports hockey `timer` is elapsed time in the period (e.g. "11" = 11 minutes played).
_PERIOD_LENGTH_MINUTES: dict[str, int] = {
    "P1": 20,
    "P2": 20,
    "P3": 20,
    "OT": 20,
    "PT": 20,
}


def _format_remaining_clock(remaining_seconds: int) -> str:
    remaining_seconds = max(0, remaining_seconds)
    minutes, seconds = divmod(remaining_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _normalize_timer(timer: Any, *, status_short: str = "") -> str | None:
    period_seconds = _PERIOD_LENGTH_MINUTES.get(status_short, 20) * 60

    if timer is None:
        return None
    if isinstance(timer, dict):
        minutes = timer.get("minutes", timer.get("minute"))
        seconds = timer.get("seconds", timer.get("second"))
        if minutes is not None and seconds is not None:
            elapsed_seconds = int(minutes) * 60 + int(seconds)
            return _format_remaining_clock(period_seconds - elapsed_seconds)
        return None

    text = str(timer).strip()
    if not text:
        return None

    elapsed_seconds: int | None = None
    if ":" in text:
        parts = text.split(":", 1)
        try:
            elapsed_seconds = int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    elif text.isdigit():
        elapsed_seconds = int(text) * 60
    else:
        return None

    if elapsed_seconds <= 0:
        return None

    return _format_remaining_clock(period_seconds - elapsed_seconds)


def _period_abbrev(status_short: str, status_long: str) -> str | None:
    if status_short in _PERIOD_ABBREV:
        return _PERIOD_ABBREV[status_short]

    long_lower = (status_long or "").lower()
    if "shootout" in long_lower:
        return "SO"
    if "overtime" in long_lower:
        return "OT"
    if "first" in long_lower:
        return "1st"
    if "second" in long_lower:
        return "2nd"
    if "third" in long_lower:
        return "3rd"
    return None


def _period_label(status_short: str, status_long: str, timer: Any) -> str | None:
    if status_short in _CANCELLED:
        return status_long or "Cancelled"
    if status_short in _FINAL:
        return "Final"
    if status_short in _SCHEDULED:
        return None

    long_lower = (status_long or "").lower()
    if status_short == "BT" or "break" in long_lower:
        return "Intermission"

    period = _period_abbrev(status_short, status_long)
    clock = _normalize_timer(timer, status_short=status_short)

    if status_short in _LIVE or period or clock:
        if clock and period:
            return f"{clock} - {period}"
        if clock:
            return clock
        if period:
            return period
        return status_long or "Live"

    return status_long or None


def _map_team(
    team: dict[str, Any],
    score: int | None,
    standings: dict[int, dict[str, Any]],
    *,
    is_scheduled: bool,
) -> dict[str, Any]:
    team_id = team.get("id")
    name = team.get("name", "Unknown")
    info: dict[str, Any] = {}
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


def map_game(raw: dict[str, Any], standings: dict[int, dict[str, Any]]) -> dict[str, Any]:
    status_short = raw.get("status", {}).get("short", "NS")
    status_long = raw.get("status", {}).get("long", "")
    game_status = _map_status(status_short)
    is_scheduled = game_status == "scheduled"

    scores = raw.get("scores") or {}
    away = raw.get("teams", {}).get("away", {})
    home = raw.get("teams", {}).get("home", {})

    return {
        "id": str(raw.get("id")),
        "league": "nhl",
        "status": game_status,
        "periodLabel": _period_label(status_short, status_long, raw.get("timer")),
        "scheduledAt": raw.get("date"),
        "venue": raw.get("week") or "",
        "awayTeam": _map_team(away, scores.get("away"), standings, is_scheduled=is_scheduled),
        "homeTeam": _map_team(home, scores.get("home"), standings, is_scheduled=is_scheduled),
    }


def get_current_season(league_payload: dict[str, Any]) -> int:
    seasons = league_payload.get("seasons") or []
    for season in seasons:
        if season.get("current"):
            return int(season["season"])
    if seasons:
        return max(int(s["season"]) for s in seasons)
    raise ValueError("No seasons found for NHL league")


async def fetch_nhl_league(client: ApiSportsClient) -> dict[str, Any]:
    payload = await client.get_hockey("leagues", {"id": NHL_LEAGUE_ID})
    rows = payload.get("response") or []
    if not rows:
        raise ValueError("NHL league not found")
    return rows[0]


def _flatten_standings_response(response: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def _format_standing_label(row: dict[str, Any]) -> str | None:
    position = row.get("position")
    if position is None:
        return None

    group_name = (row.get("group") or {}).get("name", "")
    label = _ordinal(int(position))

    if "division" in group_name.lower():
        division = group_name.replace(" Division", "").strip()
        short = {
            "Atlantic": "Atl",
            "Metropolitan": "Metro",
            "Central": "Cent",
            "Pacific": "Pac",
        }.get(division, division[:4])
        return f"{label} {short}"

    if "conference" in group_name.lower():
        conference = group_name.replace(" Conference", "").strip()
        short = {"Eastern": "East", "Western": "West"}.get(conference, conference[:4])
        return f"{label} {short}"

    return label


def _standings_info_from_row(row: dict[str, Any]) -> dict[str, Any]:
    team = row.get("team") or {}
    games = row.get("games") or {}
    return {
        "record": _format_record(games) if games else "—",
        "standing": _format_standing_label(row),
        "position": row.get("position"),
        "teamName": team.get("name"),
    }


def _pick_standings_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    regular_season = [
        row
        for row in rows
        if "regular season" in str(row.get("stage", "")).lower()
        and "pre-season" not in str(row.get("stage", "")).lower()
    ]
    pool = regular_season if regular_season else rows

    division_rows = [
        row
        for row in pool
        if "division" in str((row.get("group") or {}).get("name", "")).lower()
    ]
    pool = division_rows if division_rows else pool

    return max(pool, key=lambda row: (row.get("games") or {}).get("played", 0))


def parse_standings_by_team(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """One standings row per team (regular-season division when available)."""
    rows_by_team: dict[int, list[dict[str, Any]]] = {}
    for row in _flatten_standings_response(payload.get("response") or []):
        team = row.get("team") or {}
        team_id = team.get("id")
        if team_id is not None:
            rows_by_team.setdefault(int(team_id), []).append(row)

    standings: dict[int, dict[str, Any]] = {}
    for team_id, team_rows in rows_by_team.items():
        best_row = _pick_standings_row(team_rows)
        if best_row is not None:
            standings[team_id] = _standings_info_from_row(best_row)
    return standings


def parse_standings_records(payload: dict[str, Any]) -> dict[int, str]:
    return {
        team_id: info["record"]
        for team_id, info in parse_standings_by_team(payload).items()
    }


async def fetch_standings_records(
    client: ApiSportsClient,
    season: int,
) -> dict[int, str]:
    payload = await client.get_hockey(
        "standings",
        {"league": NHL_LEAGUE_ID, "season": season},
    )
    return parse_standings_records(payload)


async def fetch_games_for_date(
    client: ApiSportsClient,
    season: int,
    game_date: date,
) -> list[dict[str, Any]]:
    payload = await client.get_hockey(
        "games",
        {
            "league": NHL_LEAGUE_ID,
            "season": season,
            "date": game_date.isoformat(),
        },
    )
    return payload.get("response") or []


async def fetch_nhl_games_window(
    client: ApiSportsClient,
    *,
    season: int,
    center: date,
    lookback_days: int = 7,
    lookahead_days: int = 3,
) -> list[dict[str, Any]]:
    start = center - timedelta(days=lookback_days)
    end = center + timedelta(days=lookahead_days)
    dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    batches = await asyncio.gather(
        *[fetch_games_for_date(client, season, d) for d in dates]
    )

    by_id: dict[int, dict[str, Any]] = {}
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


