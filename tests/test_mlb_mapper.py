from app.services.mlb import map_game, parse_standings_by_team


def test_map_game_live_inning():
    raw = {
        "id": 178851,
        "date": "2026-05-29T00:05:00+00:00",
        "status": {"short": "IN4", "long": "Inning 4"},
        "teams": {
            "away": {"id": 15, "name": "Houston Astros"},
            "home": {"id": 35, "name": "Texas Rangers"},
        },
        "scores": {
            "away": {"total": 5},
            "home": {"total": 1},
        },
    }
    records = {15: {"record": "30-20", "standing": "1st AL West"}, 35: "25-25"}

    game = map_game(raw, records)

    assert game["status"] == "live"
    assert game["periodLabel"] == "Inning 4"
    assert game["league"] == "mlb"
    assert game["awayTeam"]["score"] == 5
    assert game["homeTeam"]["score"] == 1
    assert game["awayTeam"]["record"] == "30-20"
    assert game["awayTeam"]["standing"] == "1st AL West"


def test_map_game_scheduled_hides_scores():
    raw = {
        "id": 2,
        "date": "2026-05-29T19:00:00+00:00",
        "status": {"short": "NS", "long": "Not Started"},
        "teams": {
            "away": {"id": 25, "name": "New York Yankees"},
            "home": {"id": 4, "name": "Baltimore Orioles"},
        },
        "scores": {
            "away": {"total": 0},
            "home": {"total": 0},
        },
    }

    game = map_game(raw, {})

    assert game["status"] == "scheduled"
    assert game["periodLabel"] is None
    assert game["awayTeam"]["score"] is None
    assert game["homeTeam"]["score"] is None


def test_map_game_final():
    raw = {
        "id": 163070,
        "date": "2024-10-01T18:32:00+00:00",
        "status": {"short": "FT", "long": "Finished"},
        "teams": {
            "away": {"id": 12, "name": "Detroit Tigers"},
            "home": {"id": 15, "name": "Houston Astros"},
        },
        "scores": {
            "away": {"total": 3},
            "home": {"total": 1},
        },
    }

    game = map_game(raw, {})

    assert game["status"] == "final"
    assert game["periodLabel"] == "Final"
    assert game["awayTeam"]["score"] == 3


def test_map_game_postponed():
    raw = {
        "id": 3,
        "date": "2026-05-29T19:00:00+00:00",
        "status": {"short": "POST", "long": "Postponed"},
        "teams": {
            "away": {"id": 25, "name": "New York Yankees"},
            "home": {"id": 4, "name": "Baltimore Orioles"},
        },
        "scores": {"away": {"total": 0}, "home": {"total": 0}},
    }

    game = map_game(raw, {})

    assert game["status"] == "scheduled"
    assert game["periodLabel"] == "Postponed"


def test_parse_standings_prefers_division_row():
    payload = {
        "response": [
            [
                {
                    "position": 1,
                    "group": {"name": "American League"},
                    "team": {"id": 25, "name": "New York Yankees"},
                    "games": {
                        "played": 162,
                        "win": {"total": 94},
                        "lose": {"total": 68},
                    },
                },
                {
                    "position": 1,
                    "group": {"name": "AL East Division"},
                    "team": {"id": 25, "name": "New York Yankees"},
                    "games": {
                        "played": 162,
                        "win": {"total": 94},
                        "lose": {"total": 68},
                    },
                },
            ]
        ]
    }

    standings = parse_standings_by_team(payload)

    assert standings[25]["record"] == "94-68"
    assert standings[25]["standing"] == "1st AL East"
