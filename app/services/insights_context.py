"""Build factual context from Redis scoreboards for LLM prompts."""

from datetime import datetime, timezone

from app.config import Settings
from app.services.h2h import load_head_to_head
from app.services.mlb_cache import (
    KEY_LEAGUE_META as MLB_LEAGUE_META,
    build_scores_payload_from_cache as build_mlb_scores,
    load_team_standings as load_mlb_standings,
)
from app.services.nhl_cache import (
    KEY_LEAGUE_META as NHL_LEAGUE_META,
    build_scores_payload_from_cache as build_nhl_scores,
    load_team_standings as load_nhl_standings,
)
from app.services.redis_store import safe_redis_get_json
from app.types import JsonObject


class FavoriteTeamContext:
    def __init__(self, row: JsonObject) -> None:
        teams = row.get("teams")
        team = teams[0] if isinstance(teams, list) and teams else teams
        if not isinstance(team, dict):
            raise ValueError("Favorite team is missing joined teams row.")

        self.team_key = str(row.get("team_id") or "")
        self.league = str(team.get("league") or "")
        self.api_team_id = int(team["api_sports_team_id"])
        self.name = str(team.get("name") or "")
        self.abbreviation = str(team.get("abbreviation") or "")


def _game_involves_team(game: JsonObject, team_id: int) -> bool:
    for side in ("home", "away"):
        mapped = game.get(f"{side}Team") or game.get(side)
        if isinstance(mapped, dict) and mapped.get("id") == team_id:
            return True
        teams = game.get("teams") or {}
        raw_side = teams.get(side) or {}
        if raw_side.get("id") == team_id:
            return True
    return False


def _summarize_mapped_game(game: JsonObject, team_id: int) -> JsonObject:
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    is_home = home.get("id") == team_id
    opponent = away if is_home else home
    opponent_id = opponent.get("id")
    return {
        "id": game.get("id"),
        "status": game.get("status"),
        "scheduledAt": game.get("scheduledAt"),
        "periodLabel": game.get("periodLabel"),
        "venue": game.get("venue"),
        "teamScore": home.get("score") if is_home else away.get("score"),
        "opponentScore": away.get("score") if is_home else home.get("score"),
        "opponentName": opponent.get("name"),
        "opponentAbbreviation": opponent.get("abbreviation"),
        "opponentApiSportsTeamId": int(opponent_id) if opponent_id is not None else None,
        "location": "home" if is_home else "away",
    }


async def _load_mapped_games(settings: Settings, league: str) -> list[JsonObject]:
    if league == "nhl":
        payload = await build_nhl_scores(settings)
    elif league == "mlb":
        payload = await build_mlb_scores(settings)
    else:
        return []

    if not payload:
        return []

    games = payload.get("games")
    return games if isinstance(games, list) else []


async def build_facts_for_favorite(
    settings: Settings,
    favorite: FavoriteTeamContext,
) -> JsonObject:
    league = favorite.league
    team_id = favorite.api_team_id

    if league == "nhl":
        meta = await safe_redis_get_json(NHL_LEAGUE_META)
        standings = await load_nhl_standings(int(meta["season"])) if meta else {}
    elif league == "mlb":
        meta = await safe_redis_get_json(MLB_LEAGUE_META)
        standings = await load_mlb_standings(int(meta["season"])) if meta else {}
    else:
        meta = None
        standings = {}

    standing = standings.get(team_id, {})
    mapped_games = await _load_mapped_games(settings, league)
    team_games = [g for g in mapped_games if _game_involves_team(g, team_id)]

    scheduled = [g for g in team_games if g.get("status") == "scheduled"]
    live = [g for g in team_games if g.get("status") == "live"]
    finals = [g for g in team_games if g.get("status") == "final"]

    scheduled.sort(key=lambda g: g.get("scheduledAt") or "")
    finals.sort(key=lambda g: g.get("scheduledAt") or "", reverse=True)

    next_game = (live or scheduled or [None])[0]
    next_game_summary = _summarize_mapped_game(next_game, team_id) if next_game else None

    season = int(meta["season"]) if meta and meta.get("season") is not None else None
    head_to_head = None
    if next_game_summary:
        opponent_id = next_game_summary.get("opponentApiSportsTeamId")
        if isinstance(opponent_id, int):
            head_to_head = await load_head_to_head(
                settings,
                league=league,
                focal_team_id=team_id,
                opponent_id=opponent_id,
                season=season,
            )

    return {
        "asOf": datetime.now(timezone.utc).isoformat(),
        "team": {
            "key": favorite.team_key,
            "league": league,
            "name": favorite.name,
            "abbreviation": favorite.abbreviation,
            "apiSportsTeamId": team_id,
            "record": standing.get("record"),
            "standing": standing.get("standing"),
        },
        "nextGame": next_game_summary,
        "headToHead": head_to_head,
        "recentGames": [_summarize_mapped_game(g, team_id) for g in finals[:5]],
        "upcomingGames": [_summarize_mapped_game(g, team_id) for g in scheduled[:3]],
    }


def pick_primary_favorite(favorites: list[FavoriteTeamContext]) -> FavoriteTeamContext | None:
    supported = [f for f in favorites if f.league in {"nhl", "mlb"}]
    return supported[0] if supported else None
