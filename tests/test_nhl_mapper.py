from app.services.nhl import map_game


def test_map_game_live_with_clock_and_period():
    raw = {
        "id": 1,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": "12:34",
        "status": {"short": "P3", "long": "Third Period"},
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 1, "home": 0},
        "week": "Quarter-finals",
    }
    records = {10: "3-2-1", 20: "2-4-0"}

    game = map_game(raw, records)

    assert game["status"] == "live"
    assert game["periodLabel"] == "12:34 - 3rd"


def test_map_game_live_api_sports_minutes_timer():
    """API-Sports sends timer as whole minutes without a colon (e.g. '11')."""
    raw = {
        "id": 425583,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": "11",
        "status": {"short": "P2", "long": "Second Period"},
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 2, "home": 0},
        "week": None,
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "11:00 - 2nd"


def test_map_game_live_period_only():
    raw = {
        "id": 4,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": None,
        "status": {"short": "P1", "long": "First Period"},
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 1, "home": 0},
        "week": None,
    }

    game = map_game(raw, {})

    assert game["status"] == "live"
    assert game["periodLabel"] == "1st"
    assert game["awayTeam"]["score"] == 1


def test_map_game_scheduled_hides_scores():
    raw = {
        "id": 2,
        "date": "2026-05-21T00:00:00+00:00",
        "timer": None,
        "status": {"short": "NS", "long": "Not Started"},
        "teams": {
            "away": {"id": 10, "name": "Vegas Golden Knights"},
            "home": {"id": 20, "name": "Colorado Avalanche"},
        },
        "scores": {"away": None, "home": None},
        "week": "Semi-finals",
    }

    game = map_game(raw, {})

    assert game["status"] == "scheduled"
    assert game["awayTeam"]["score"] is None
    assert game["homeTeam"]["score"] is None


def test_map_game_cancelled():
    raw = {
        "id": 3,
        "date": "2026-05-20T00:00:00+00:00",
        "timer": None,
        "status": {"short": "CANC", "long": "Cancelled"},
        "teams": {
            "away": {"id": 10, "name": "Boston Bruins"},
            "home": {"id": 20, "name": "Toronto Maple Leafs"},
        },
        "scores": {"away": 0, "home": 0},
        "week": None,
    }

    game = map_game(raw, {})

    assert game["status"] == "final"
    assert game["periodLabel"] == "Cancelled"
