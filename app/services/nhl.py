import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any

from app.services.api_sports import ApiSportsClient

logger = logging.getLogger(__name__)

NHL_LEAGUE_ID = 57
NHL_GAMES_CACHE_TTL_SECONDS = 45

# API-Sports status.short values
_SCHEDULED = frozenset({"NS", "TBD"})
_LIVE = frozenset({"P1", "P2", "P3", "OT", "PT", "BT", "LIVE"})
_FINAL = frozenset({"FT", "AP", "AOT", "PEN", "AW", "WO"})
_CANCELLED = frozenset({"CANC", "ABD"})

_nhl_scores_cache: dict[str, tuple[float, dict[str, Any]]] = {}

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


def _period_label(status_short: str, status_long: str, timer: str | None) -> str | None:
    if status_short in _CANCELLED:
        return status_long or "Cancelled"
    if status_short in _FINAL:
        return "Final"
    if status_short in _SCHEDULED:
        return None
    if timer and ":" in str(timer):
        return str(timer)
    if status_short in _LIVE:
        return status_long
    return status_long


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


async def fetch_standings_records(
    client: ApiSportsClient,
    season: int,
) -> dict[int, str]:
    payload = await client.get_hockey(
        "standings",
        {"league": NHL_LEAGUE_ID, "season": season},
    )
    records: dict[int, str] = {}
    response = payload.get("response") or []

    rows: list[dict[str, Any]] = []
    for item in response:
        if isinstance(item, list):
            rows.extend(item)
        elif isinstance(item, dict):
            rows.append(item)

    for row in rows:
        team = row.get("team") or {}
        team_id = team.get("id")
        games = row.get("games")
        if team_id is not None and games:
            records[team_id] = _format_record(games)
    return records


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


async def build_nhl_scores_payload(
    client: ApiSportsClient,
    *,
    game_date: date | None = None,
) -> dict[str, Any]:
    center = game_date or datetime.now(timezone.utc).date()
    cache_key = center.isoformat()
    now = monotonic()
    cached = _nhl_scores_cache.get(cache_key)
    if cached and (now - cached[0]) < NHL_GAMES_CACHE_TTL_SECONDS:
        return cached[1]

    league = await fetch_nhl_league(client)
    season = get_current_season(league)
    records = await fetch_standings_records(client, season)
    raw_games = await fetch_nhl_games_window(client, season=season, center=center)
    games = [map_game(g, records) for g in raw_games]

    payload = {
        "status": "ok",
        "league": {
            "id": league.get("id"),
            "name": league.get("name"),
            "logo": league.get("logo"),
            "season": season,
        },
        "date": center.isoformat(),
        "message": f"Fetched {len(games)} NHL games.",
        "games": games,
    }
    _nhl_scores_cache[cache_key] = (now, payload)
    return payload
