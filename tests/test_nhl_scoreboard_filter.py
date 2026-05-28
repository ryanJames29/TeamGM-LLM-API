from datetime import date

from app.services.nhl_cache import filter_games_for_scoreboard


def _teams(home_id: int, away_id: int) -> dict:
    return {
        "home": {"id": home_id, "name": f"Team {home_id}"},
        "away": {"id": away_id, "name": f"Team {away_id}"},
    }


def test_scoreboard_today_plus_tomorrow_for_teams_off_today():
    today = date(2026, 5, 18)
    tomorrow = date(2026, 5, 19)
    games = [
        {
            "id": 1,
            "date": f"{today.isoformat()}T23:00:00+00:00",
            "status": {"short": "FT", "long": "Final"},
            "teams": _teams(10, 20),
        },
        {
            "id": 2,
            "date": f"{tomorrow.isoformat()}T23:00:00+00:00",
            "status": {"short": "NS", "long": "Not Started"},
            "teams": _teams(10, 30),
        },
        {
            "id": 3,
            "date": f"{tomorrow.isoformat()}T23:30:00+00:00",
            "status": {"short": "NS", "long": "Not Started"},
            "teams": _teams(40, 50),
        },
        {
            "id": 4,
            "date": "2026-05-17T23:00:00+00:00",
            "status": {"short": "FT", "long": "Final"},
            "teams": _teams(60, 70),
        },
    ]

    result = filter_games_for_scoreboard(games, today=today)

    assert {g["id"] for g in result} == {1, 3}


def test_scoreboard_includes_live_even_from_previous_day():
    today = date(2026, 5, 18)
    games = [
        {
            "id": 5,
            "date": "2026-05-17T23:30:00+00:00",
            "status": {"short": "P2", "long": "Second Period"},
            "teams": _teams(80, 90),
        },
    ]

    result = filter_games_for_scoreboard(games, today=today)

    assert [g["id"] for g in result] == [5]


def test_scoreboard_excludes_stale_live_from_old_dates():
    today = date(2026, 5, 28)
    games = [
        {
            "id": 425583,
            "date": "2026-05-18T23:30:00+00:00",
            "status": {"short": "OT", "long": "Over Time"},
            "teams": _teams(674, 688),
        },
        {
            "id": 425602,
            "date": f"{today.isoformat()}T23:30:00+00:00",
            "status": {"short": "BT", "long": "Break Time"},
            "teams": _teams(10, 20),
        },
    ]

    result = filter_games_for_scoreboard(games, today=today)

    assert [g["id"] for g in result] == [425602]
