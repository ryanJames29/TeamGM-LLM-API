from app.services.nhl import parse_standings_records


def test_parse_standings_records_nested_groups():
    payload = {
        "response": [
            [
                {
                    "team": {"id": 10, "name": "Montreal Canadiens"},
                    "games": {
                        "win": {"total": 3},
                        "lose": {"total": 2},
                        "lose_overtime": {"total": 1},
                    },
                }
            ]
        ]
    }

    records = parse_standings_records(payload)

    assert records[10] == "3-2-1"
