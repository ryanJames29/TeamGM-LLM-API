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
    assert game["periodLabel"] == "7:26 - 3rd"


def test_map_game_live_api_sports_minutes_timer():
    """API-Sports timer is elapsed minutes in the period (11 → 9:00 left in a 20-min period)."""
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

    assert game["periodLabel"] == "9:00 - 2nd"


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


def test_map_game_break_time_shows_intermission():
    raw = {
        "id": 5,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": None,
        "status": {"short": "BT", "long": "Break Time"},
        "teams": {
            "away": {"id": 10, "name": "Boston Bruins"},
            "home": {"id": 20, "name": "Toronto Maple Leafs"},
        },
        "scores": {"away": 1, "home": 1},
        "week": None,
    }

    game = map_game(raw, {})

    assert game["status"] == "live"
    assert game["periodLabel"] == "Intermission"


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


def test_map_game_live_overtime_five_minute_period():
    """Regular-season OT is 5 minutes; timer is elapsed minutes in the period."""
    raw = {
        "id": 99,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": "4",
        "status": {"short": "OT", "long": "Overtime"},
        "periods": {
            "first": "1-0",
            "second": "0-1",
            "third": "1-0",
            "overtime": "0-0",
            "penalties": None,
        },
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 2, "home": 2},
        "week": "18",
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "1:00 - OT"


def test_map_game_live_playoff_overtime_twenty_minute_period():
    """Playoff OT is 20 minutes (API-Sports timer still elapsed minutes)."""
    raw = {
        "id": 425583,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": "11",
        "status": {"short": "OT", "long": "Over Time"},
        "periods": {
            "first": "0-2",
            "second": "1-0",
            "third": "1-0",
            "overtime": "0-0",
            "penalties": None,
        },
        "teams": {
            "away": {"id": 688, "name": "Montreal Canadiens"},
            "home": {"id": 674, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 2, "home": 2},
        "week": "Quarter-finals",
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "9:00 - OT"


def test_map_game_mislabeled_ot_during_third_period():
    """API-Sports sometimes sends OT while the 3rd period is in progress."""
    raw = {
        "id": 425602,
        "date": "2026-05-28T23:30:00+00:00",
        "timer": "11",
        "status": {"short": "OT", "long": "Over Time"},
        "periods": {
            "first": "0-3",
            "second": "0-0",
            "third": None,
            "overtime": None,
            "penalties": None,
        },
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 3, "home": 0},
        "week": "Semi-finals",
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "9:00 - 3rd"


def test_map_game_pre_overtime_intermission():
    """Tied after regulation: intermission before OT, even if status.short is OT."""
    raw = {
        "id": 100,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": None,
        "status": {"short": "OT", "long": "Over Time"},
        "periods": {
            "first": "1-0",
            "second": "0-1",
            "third": "1-0",
            "overtime": None,
            "penalties": None,
        },
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 2, "home": 2},
        "week": "Quarter-finals",
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "Intermission"


def test_map_game_penalties_time_is_shootout():
    raw = {
        "id": 101,
        "date": "2026-05-18T23:30:00+00:00",
        "timer": None,
        "status": {"short": "PT", "long": "Penalties Time"},
        "periods": {
            "first": "1-0",
            "second": "0-1",
            "third": "1-0",
            "overtime": "0-0",
            "penalties": "0-0",
        },
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 2, "home": 2},
        "week": None,
    }

    game = map_game(raw, {})

    assert game["periodLabel"] == "SO"


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
