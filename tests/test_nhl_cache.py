from datetime import date

from app.services.nhl_cache import filter_games_in_window


def test_filter_games_in_window():
    center = date(2026, 5, 18)
    games = [
        {"id": 1, "date": "2026-05-10T00:00:00+00:00", "timestamp": 1},
        {"id": 2, "date": "2026-05-18T12:00:00+00:00", "timestamp": 2},
        {"id": 3, "date": "2026-05-25T00:00:00+00:00", "timestamp": 3},
        {"id": 4, "date": "2026-06-01T00:00:00+00:00", "timestamp": 4},
    ]

    result = filter_games_in_window(games, center, lookback_days=7, lookahead_days=3)

    assert [g["id"] for g in result] == [2]
