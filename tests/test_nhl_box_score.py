from app.services.nhl_detail import build_nhl_box_score


def test_build_nhl_box_score_period_lines_match_team_totals():
    """Period rows use home-away strings; totals use scores.away / scores.home."""
    raw = {
        "periods": {
            "first": "0-2",
            "second": "1-0",
            "third": "1-0",
            "overtime": None,
            "penalties": None,
        },
        "scores": {"away": 2, "home": 2},
    }

    box = build_nhl_box_score(raw)

    first = next(row for row in box["periods"] if row["label"] == "1st")
    assert first == {"label": "1st", "away": 2, "home": 0}

    away_period_sum = sum(row["away"] for row in box["periods"])
    home_period_sum = sum(row["home"] for row in box["periods"])
    assert away_period_sum == box["away"]["goals"]
    assert home_period_sum == box["home"]["goals"]
