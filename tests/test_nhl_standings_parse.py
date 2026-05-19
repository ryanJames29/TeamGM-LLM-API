from app.services.nhl import parse_standings_by_team, parse_standings_records


def test_parse_standings_records_nested_groups():
    payload = {
        "response": [
            [
                {
                    "stage": "NHL - Regular Season",
                    "position": 3,
                    "group": {"name": "Atlantic Division"},
                    "team": {"id": 10, "name": "Montreal Canadiens"},
                    "games": {
                        "played": 82,
                        "win": {"total": 34},
                        "lose": {"total": 24},
                        "lose_overtime": {"total": 10},
                    },
                }
            ]
        ]
    }

    records = parse_standings_records(payload)
    by_team = parse_standings_by_team(payload)

    assert records[10] == "34-24-10"
    assert by_team[10]["standing"] == "3rd Atl"


def test_parse_standings_prefers_regular_season_over_preseason():
    payload = {
        "response": [
            {
                "stage": "NHL - Regular Season",
                "position": 1,
                "group": {"name": "Atlantic Division"},
                "team": {"id": 674, "name": "Buffalo Sabres"},
                "games": {
                    "played": 82,
                    "win": {"total": 42},
                    "lose": {"total": 23},
                    "lose_overtime": {"total": 9},
                },
            },
            {
                "stage": "NHL - Pre-season",
                "position": 5,
                "group": {"name": "Atlantic Division"},
                "team": {"id": 674, "name": "Buffalo Sabres"},
                "games": {
                    "played": 6,
                    "win": {"total": 3},
                    "lose": {"total": 2},
                    "lose_overtime": {"total": 1},
                },
            },
        ]
    }

    by_team = parse_standings_by_team(payload)

    assert by_team[674]["record"] == "42-23-9"
    assert by_team[674]["standing"] == "1st Atl"
