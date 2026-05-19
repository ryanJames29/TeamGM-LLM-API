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

# API-Sports hockey timer is usually whole minutes remaining in the period (e.g. "11" → 11:00).
_PERIOD_LENGTH_MINUTES: dict[str, int] = {
    "P1": 20,
    "P2": 20,
    "P3": 20,
    "OT": 20,
    "PT": 20,
}


def _normalize_timer(timer: Any, *, status_short: str = "") -> str | None:
    if timer is None:
        return None
    if isinstance(timer, dict):
        minutes = timer.get("minutes", timer.get("minute"))
        seconds = timer.get("seconds", timer.get("second"))
        if minutes is not None and seconds is not None:
            return f"{int(minutes)}:{int(seconds):02d}"
        return None

    text = str(timer).strip()
    if not text:
        return None

    if ":" in text:
        parts = text.split(":", 1)
        try:
            minutes = int(parts[0])
            seconds = int(parts[1])
            return f"{minutes}:{seconds:02d}"
        except ValueError:
            return text

    if text.isdigit():
        value = int(text)
        if value <= 0:
            return None
        period_cap = _PERIOD_LENGTH_MINUTES.get(status_short, 20)
        # Whole minutes left in period (typical API-Sports hockey shape).
        if value <= period_cap:
            return f"{value}:00"
        # Fallback: treat as seconds remaining (e.g. 47 → 0:47).
        if value < 60:
            return f"0:{value:02d}"
        return f"{value // 60}:{value % 60:02d}"

    return None


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
    records: dict[int, str],
    *,
    is_scheduled: bool,
) -> dict[str, Any]:
    team_id = team.get("id")
    name = team.get("name", "Unknown")
    record = records.get(team_id, "—") if team_id is not None else "—"

    return {
        "name": name,
        "abbreviation": _team_abbreviation(name),
        "record": record,
        "score": None if is_scheduled else score,
    }


def map_game(raw: dict[str, Any], records: dict[int, str]) -> dict[str, Any]:
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
        "awayTeam": _map_team(away, scores.get("away"), records, is_scheduled=is_scheduled),
        "homeTeam": _map_team(home, scores.get("home"), records, is_scheduled=is_scheduled),
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


def parse_standings_records(payload: dict[str, Any]) -> dict[int, str]:
    records: dict[int, str] = {}
    for row in _flatten_standings_response(payload.get("response") or []):
        team = row.get("team") or {}
        team_id = team.get("id")
        games = row.get("games")
        if team_id is not None and games:
            records[team_id] = _format_record(games)
    return records


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


