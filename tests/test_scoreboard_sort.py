from app.services.nhl_cache import sort_scoreboard_games


def test_sort_scoreboard_games_live_first():
    games = [
        {"id": "1", "status": "final", "scheduledAt": "2026-05-18T20:00:00Z"},
        {"id": "2", "status": "live", "scheduledAt": "2026-05-18T23:00:00Z"},
        {"id": "3", "status": "scheduled", "scheduledAt": "2026-05-19T23:00:00Z"},
        {"id": "4", "status": "scheduled", "scheduledAt": "2026-05-18T22:00:00Z"},
    ]

    sorted_games = sort_scoreboard_games(games)

    assert [g["id"] for g in sorted_games] == ["2", "4", "3", "1"]
