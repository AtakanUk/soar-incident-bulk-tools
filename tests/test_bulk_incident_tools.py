from unittest.mock import MagicMock

import bulk_incident_tools as tools


def test_parse_iso8601_returns_epoch_milliseconds() -> None:
    assert tools.parse_iso8601("1970-01-01T00:00:01Z") == 1000
    assert tools.parse_iso8601("1970-01-01T00:00:01") == 1000


def test_find_incidents_pages_until_limit() -> None:
    client = MagicMock()
    pages = [
        {"data": [{"id": i} for i in range(500)]},
        {"data": [{"id": i} for i in range(500, 700)]},
    ]
    client.post.side_effect = pages
    found = tools.find_incidents(client, 1, 2, limit=650)
    assert len(found) == 700  # second page asked for 150 but the fake returns more
    assert client.post.call_args_list[1].args[1]["start"] == 500
    assert client.post.call_args_list[1].args[1]["length"] == 150


def test_find_incidents_stops_on_short_page() -> None:
    client = MagicMock()
    client.post.return_value = {"data": [{"id": 1}]}
    assert tools.find_incidents(client, 1, 2, limit=100) == [{"id": 1}]
    assert client.post.call_count == 1


def test_resolution_changes() -> None:
    assert tools.resolution_changes("Done", "Not an Issue", close=True) == {
        "resolution_id": "Not an Issue",
        "resolution_summary": "Done",
        "plan_status": "C",
    }
    assert tools.resolution_changes("Done", "3460", close=False) == {
        "resolution_id": 3460,
        "resolution_summary": "Done",
    }


def test_dry_run_does_not_delete(monkeypatch, capsys) -> None:
    client = MagicMock()
    client.post.return_value = {"data": [{"id": 7}, {"id": 8}]}
    monkeypatch.setattr(tools, "get_client_from_env", lambda: client)
    code = tools.main(
        ["delete", "--start", "2026-01-01T00:00:00Z", "--end", "2026-01-01T01:00:00Z"]
    )
    assert code == 0
    client.delete.assert_not_called()
    assert '"dry_run": true' in capsys.readouterr().out


def test_failures_are_reported(monkeypatch) -> None:
    client = MagicMock()
    client.post.return_value = {"data": [{"id": 7}, {"id": 8}]}
    client.delete.side_effect = [None, RuntimeError("locked")]
    monkeypatch.setattr(tools, "get_client_from_env", lambda: client)
    code = tools.main(
        ["delete", "--start", "2026-01-01T00:00:00Z", "--end", "2026-01-01T01:00:00Z", "--confirm"]
    )
    assert code == 1
    assert client.delete.call_count == 2
