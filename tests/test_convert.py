from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

import app as fx_app


VALID_PARAMS = {
    "amount": "250",
    "from": "EUR",
    "to": "TRY",
    "date": "2026-08-28",
}


class FakeUpstream:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler = self._unexpected_request

    @staticmethod
    def _unexpected_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected upstream request: {request.url}")

    def dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def return_rate(self, rate: str, rate_date: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            target = request.url.params["symbols"]
            body = f'{{"date":"{rate_date}","rates":{{"{target}":{rate}}}}}'
            return httpx.Response(200, content=body.encode())

        self.handler = handler

    def return_json(self, payload: object, status_code: int = 200) -> None:
        self.handler = lambda _request: httpx.Response(status_code, json=payload)

    def return_status(self, status_code: int) -> None:
        self.handler = lambda _request: httpx.Response(
            status_code, text="private upstream detail"
        )

    def raise_error(self, error: Exception) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise error

        self.handler = handler


@pytest.fixture(autouse=True)
def fake_upstream(monkeypatch: pytest.MonkeyPatch):
    fake = FakeUpstream()
    transport = httpx.MockTransport(fake.dispatch)
    real_async_client = httpx.AsyncClient

    def client_factory(**kwargs) -> httpx.AsyncClient:
        return real_async_client(transport=transport, **kwargs)

    fx_app._rate_cache.clear()
    monkeypatch.setattr(fx_app.httpx, "AsyncClient", client_factory)
    yield fake
    fx_app._rate_cache.clear()


@pytest.fixture
def client():
    with TestClient(fx_app.app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_error(response, status_code: int, error: str) -> None:
    assert response.status_code == status_code
    assert set(response.json()) == {"error", "message"}
    assert response.json()["error"] == error


def test_normal_business_day_conversion(client, fake_upstream):
    fake_upstream.return_rate("47.1234", "2026-08-28")

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
    }
    request = fake_upstream.requests[0]
    assert request.url.path == "/v1/2026-08-28"
    assert dict(request.url.params) == {"base": "EUR", "symbols": "TRY"}


def test_lowercase_currencies_are_normalized(client, fake_upstream):
    fake_upstream.return_rate("47.1234", "2026-08-28")

    response = client.get(
        "/tools/convert", params={**VALID_PARAMS, "from": "eur", "to": "try"}
    )

    assert response.status_code == 200
    assert response.json()["from"] == "EUR"
    assert response.json()["to"] == "TRY"
    assert dict(fake_upstream.requests[0].url.params) == {
        "base": "EUR",
        "symbols": "TRY",
    }


def test_weekend_uses_authoritative_earlier_rate_date(client, fake_upstream):
    fake_upstream.return_rate("47.1234", "2026-08-28")

    response = client.get(
        "/tools/convert", params={**VALID_PARAMS, "date": "2026-08-30"}
    )

    assert response.status_code == 200
    assert response.json()["asked_date"] == "2026-08-30"
    assert response.json()["rate_date"] == "2026-08-28"


@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [
        ("100", "1.23456", 123.46),
        ("1", "1.005", 1.01),
    ],
)
def test_decimal_precision_and_round_half_up(
    client, fake_upstream, amount, rate, expected
):
    fake_upstream.return_rate(rate, "2026-08-28")

    response = client.get(
        "/tools/convert", params={**VALID_PARAMS, "amount": amount}
    )

    assert response.status_code == 200
    assert response.json()["result"] == expected


def test_amount_with_ten_decimal_places_is_accepted(client, fake_upstream):
    fake_upstream.return_rate("2.5", "2026-08-28")

    response = client.get(
        "/tools/convert", params={**VALID_PARAMS, "amount": "1.1234567890"}
    )

    assert response.status_code == 200
    assert response.json()["result"] == 2.81


@pytest.mark.parametrize(
    ("changes", "remove", "status_code", "error"),
    [
        ({}, "amount", 422, "invalid_request"),
        ({}, "from", 422, "invalid_request"),
        ({}, "to", 422, "invalid_request"),
        ({}, "date", 422, "invalid_request"),
        ({"amount": "not-a-number"}, None, 422, "invalid_request"),
        ({"amount": "0"}, None, 400, "invalid_amount"),
        ({"amount": "-1"}, None, 400, "invalid_amount"),
        ({"amount": "NaN"}, None, 400, "invalid_amount"),
        ({"amount": "Infinity"}, None, 400, "invalid_amount"),
        ({"amount": "-Infinity"}, None, 400, "invalid_amount"),
        ({"from": "EU1"}, None, 400, "invalid_currency"),
        ({"to": "eur"}, None, 400, "same_currency"),
        ({"date": "not-a-date"}, None, 422, "invalid_request"),
        (
            {"date": (date.today() + timedelta(days=1)).isoformat()},
            None,
            400,
            "invalid_date",
        ),
        ({"date": "1999-01-03"}, None, 404, "rate_unavailable"),
    ],
)
def test_request_validation(
    client, fake_upstream, changes, remove, status_code, error
):
    params = {**VALID_PARAMS, **changes}
    if remove:
        params.pop(remove)

    response = client.get("/tools/convert", params=params)

    assert_error(response, status_code, error)
    assert fake_upstream.requests == []


def test_extreme_decimal_is_a_controlled_invalid_amount(client, fake_upstream):
    fake_upstream.return_rate("1.25", "2026-08-28")

    response = client.get(
        "/tools/convert", params={**VALID_PARAMS, "amount": "1E+100000"}
    )

    assert_error(response, 400, "invalid_amount")


@pytest.mark.parametrize(
    ("upstream_status", "status_code", "error"),
    [
        (500, 502, "upstream_unavailable"),
        (408, 502, "upstream_unavailable"),
        (429, 502, "upstream_unavailable"),
        (400, 400, "invalid_currency"),
        (422, 400, "invalid_currency"),
        (404, 404, "rate_unavailable"),
        (418, 502, "upstream_invalid_response"),
    ],
)
def test_upstream_http_statuses(
    client, fake_upstream, upstream_status, status_code, error
):
    fake_upstream.return_status(upstream_status)

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, status_code, error)
    assert "private upstream detail" not in response.text


@pytest.mark.parametrize(
    ("exception_type", "status_code", "error"),
    [
        (httpx.ReadTimeout, 504, "upstream_timeout"),
        (httpx.ConnectError, 502, "upstream_unavailable"),
    ],
)
def test_upstream_request_failures(
    client, fake_upstream, exception_type, status_code, error
):
    request = httpx.Request("GET", "http://fake-upstream")
    fake_upstream.raise_error(exception_type("failure", request=request))

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, status_code, error)


def test_non_json_upstream_response(client, fake_upstream):
    fake_upstream.handler = lambda _request: httpx.Response(200, text="not json")

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "upstream_invalid_response")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"date": "2026-08-28"},
        {"date": "2026-08-28", "rates": {"USD": 1}},
        {"rates": {"TRY": 1}},
        {"date": "invalid-date", "rates": {"TRY": 1}},
        {"date": "2026-08-28", "rates": {"TRY": 0}},
        {"date": "2026-08-28", "rates": {"TRY": -1}},
        {"date": "2026-08-28", "rates": {"TRY": "not-numeric"}},
        {"date": "2026-08-28", "rates": {"TRY": True}},
        {"date": "2026-08-29", "rates": {"TRY": 1}},
    ],
)
def test_invalid_upstream_payloads(client, fake_upstream, payload):
    fake_upstream.return_json(payload)

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "upstream_invalid_response")


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_upstream_rates(client, fake_upstream, rate):
    body = f'{{"date":"2026-08-28","rates":{{"TRY":{rate}}}}}'
    fake_upstream.handler = lambda _request: httpx.Response(
        200, content=body.encode()
    )

    response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "upstream_invalid_response")


def test_identical_rate_questions_call_upstream_once(client, fake_upstream):
    fake_upstream.return_rate("1.2", "2026-08-28")

    client.get("/tools/convert", params=VALID_PARAMS)
    client.get("/tools/convert", params=VALID_PARAMS)

    assert len(fake_upstream.requests) == 1


def test_different_amounts_reuse_rate(client, fake_upstream):
    fake_upstream.return_rate("1.2", "2026-08-28")

    first = client.get(
        "/tools/convert", params={**VALID_PARAMS, "amount": "100"}
    )
    second = client.get(
        "/tools/convert", params={**VALID_PARAMS, "amount": "500"}
    )

    assert first.json()["result"] == 120
    assert second.json()["result"] == 600
    assert len(fake_upstream.requests) == 1


def test_different_dates_do_not_share_cache(client, fake_upstream):
    fake_upstream.return_rate("1.2", "2026-08-28")

    client.get("/tools/convert", params=VALID_PARAMS)
    client.get(
        "/tools/convert", params={**VALID_PARAMS, "date": "2026-08-27"}
    )

    assert len(fake_upstream.requests) == 2


def test_different_currency_pairs_do_not_share_cache(client, fake_upstream):
    fake_upstream.return_rate("1.2", "2026-08-28")

    client.get("/tools/convert", params=VALID_PARAMS)
    client.get("/tools/convert", params={**VALID_PARAMS, "to": "USD"})

    assert len(fake_upstream.requests) == 2


def test_failed_upstream_lookup_is_not_cached(client, fake_upstream):
    fake_upstream.return_status(500)

    first = client.get("/tools/convert", params=VALID_PARAMS)
    second = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(first, 502, "upstream_unavailable")
    assert_error(second, 502, "upstream_unavailable")
    assert len(fake_upstream.requests) == 2


def test_upstream_base_is_part_of_cache_key(client, fake_upstream, monkeypatch):
    fake_upstream.return_rate("1.2", "2026-08-28")

    client.get("/tools/convert", params=VALID_PARAMS)
    monkeypatch.setattr(fx_app, "FX_UPSTREAM_BASE", "http://another-upstream")
    client.get("/tools/convert", params=VALID_PARAMS)

    assert len(fake_upstream.requests) == 2
    assert fake_upstream.requests[1].url.host == "another-upstream"
