from unittest.mock import Mock, patch

import pytest
import requests

import dependabotalerts


ALERTS_URL = "https://api.github.com/orgs/NOAA-GSL/dependabot/alerts?state=open&per_page=100"
NEXT_URL = ALERTS_URL + "&after=cursor123"


def make_response(alerts, next_url=None):
    response = Mock()
    response.json.return_value = alerts
    response.links = {"next": {"url": next_url}} if next_url else {}
    return response


def test_fetches_repository_alerts_from_later_pages():
    first_alert = {"state": "open", "repository": {"name": "another-repo"}}
    missing_alert = {
        "state": "open",
        "repository": {"name": "PrincessFITARABot"},
        "security_advisory": {"severity": "high"},
    }
    first_page = make_response([first_alert], NEXT_URL)
    second_page = make_response([missing_alert, {"state": "fixed"}])

    with patch.object(dependabotalerts.requests, "get", side_effect=[first_page, second_page]) as get:
        alerts = dependabotalerts.get_dependabot_alerts("NOAA-GSL")

    assert alerts == [first_alert, missing_alert]
    assert [call.args[0] for call in get.call_args_list] == [ALERTS_URL, NEXT_URL]
    for call in get.call_args_list:
        assert call.kwargs == {
            "headers": dependabotalerts.HEADERS,
            "timeout": dependabotalerts.REQUEST_TIMEOUT,
        }


@pytest.mark.parametrize("limits", [{"max_pages": 1}, {"max_total": 1}])
def test_diagnostic_limits_stop_pagination_with_warning(limits, capsys):
    alert = {"state": "open"}
    with patch.object(dependabotalerts.requests, "get", return_value=make_response([alert], NEXT_URL)) as get:
        assert dependabotalerts.get_dependabot_alerts("NOAA-GSL", **limits) == [alert]

    get.assert_called_once()
    assert "report may be incomplete" in capsys.readouterr().out


def test_max_total_truncates_alerts_across_pages():
    first_alert = {"state": "open", "number": 1}
    second_alert = {"state": "open", "number": 2}
    third_alert = {"state": "open", "number": 3}
    pages = [make_response([first_alert], NEXT_URL), make_response([second_alert, third_alert])]
    with patch.object(dependabotalerts.requests, "get", side_effect=pages):
        assert dependabotalerts.get_dependabot_alerts("NOAA-GSL", max_total=2) == [first_alert, second_alert]


def test_empty_response_finishes_without_extra_requests():
    with patch.object(dependabotalerts.requests, "get", return_value=make_response([])) as get:
        assert dependabotalerts.get_dependabot_alerts("NOAA-GSL") == []
    get.assert_called_once()


@pytest.mark.parametrize("error", [requests.HTTPError("403 Forbidden"), requests.Timeout("timed out")])
def test_later_page_failure_does_not_return_partial_results(error):
    first_page = make_response([{"state": "open"}], NEXT_URL)
    with patch.object(dependabotalerts.requests, "get", side_effect=[first_page, error]):
        with pytest.raises(type(error)):
            dependabotalerts.get_dependabot_alerts("NOAA-GSL")


def test_unexpected_response_does_not_return_partial_results():
    pages = [make_response([{"state": "open"}], NEXT_URL), make_response({"message": "error"})]
    with patch.object(dependabotalerts.requests, "get", side_effect=pages):
        with pytest.raises(ValueError, match="expected list"):
            dependabotalerts.get_dependabot_alerts("NOAA-GSL")