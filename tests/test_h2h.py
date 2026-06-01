from app.services.h2h import _build_h2h_summary, _summarize_h2h_game


def test_summarize_h2h_game_nhl():
    raw = {
        "date": "2026-03-01T00:00:00+00:00",
        "teams": {
            "away": {"id": 10, "name": "Montreal Canadiens"},
            "home": {"id": 20, "name": "Buffalo Sabres"},
        },
        "scores": {"away": 3, "home": 2},
    }

    summary = _summarize_h2h_game(raw, focal_team_id=10, league="nhl")

    assert summary["result"] == "win"
    assert summary["focalScore"] == 3
    assert summary["opponentScore"] == 2
    assert summary["location"] == "away"


def test_build_h2h_summary():
    games = [
        {
            "date": "2026-03-01T00:00:00+00:00",
            "teams": {
                "away": {"id": 10, "name": "Montreal Canadiens"},
                "home": {"id": 20, "name": "Buffalo Sabres"},
            },
            "scores": {"away": 3, "home": 2},
        },
        {
            "date": "2026-02-01T00:00:00+00:00",
            "teams": {
                "away": {"id": 20, "name": "Buffalo Sabres"},
                "home": {"id": 10, "name": "Montreal Canadiens"},
            },
            "scores": {"away": 1, "home": 4},
        },
    ]

    summary = _build_h2h_summary(
        games,
        focal_team_id=10,
        opponent_id=20,
        league="nhl",
    )

    assert summary["sampleSize"] == 2
    assert summary["focalTeamWins"] == 2
    assert summary["focalTeamLosses"] == 0
