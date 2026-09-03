"""FastAPI application for the FX conversion tool."""

import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


DEFAULT_FX_UPSTREAM_BASE = "https://api.frankfurter.dev"
FX_UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", DEFAULT_FX_UPSTREAM_BASE).rstrip("/")
HTTP_TIMEOUT_SECONDS = 5.0
RESULT_QUANTUM = Decimal("0.01")
SERIES_START_DATE = date(1999, 1, 4)

app = FastAPI(title="FX conversion tool")

RateCacheKey = tuple[str, str, str, date]
RateCacheValue = tuple[Decimal, date]
_rate_cache: dict[RateCacheKey, RateCacheValue] = {}


class APIError(Exception):
    """A customer-safe application error."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message


def error_response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message},
    )


def invalid_upstream_response() -> APIError:
    return APIError(
        502,
        "upstream_invalid_response",
        "The rate provider returned an invalid response.",
    )


@app.exception_handler(APIError)
async def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.status_code, exc.error, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_request_validation(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    non_finite_amount = any(
        error["loc"][-1] == "amount" and error["type"] == "finite_number"
        for error in exc.errors()
    )
    if non_finite_amount:
        return error_response(400, "invalid_amount", "Amount must be finite and positive.")
    return error_response(422, "invalid_request", "Request parameters are missing or invalid.")


@app.exception_handler(Exception)
async def handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
    return error_response(500, "internal_error", "The conversion could not be completed.")


async def fetch_historical_rate(
    base: str, target: str, asked_date: date
) -> tuple[Decimal, date]:
    """Fetch a historical rate and the publication date reported upstream."""
    cache_key = (FX_UPSTREAM_BASE, base, target, asked_date)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    url = f"{FX_UPSTREAM_BASE}/v1/{asked_date.isoformat()}"
    params = {"base": base, "symbols": target}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        raise APIError(504, "upstream_timeout", "The rate provider timed out.") from exc
    except httpx.RequestError as exc:
        raise APIError(
            502, "upstream_unavailable", "The rate provider is unavailable."
        ) from exc

    if response.status_code in {400, 422}:
        raise APIError(400, "invalid_currency", "A currency is not supported.")
    if response.status_code == 404:
        raise APIError(404, "rate_unavailable", "A rate is unavailable for this request.")
    if response.status_code >= 500 or response.status_code in {408, 429}:
        raise APIError(502, "upstream_unavailable", "The rate provider is unavailable.")
    if not 200 <= response.status_code < 300:
        raise invalid_upstream_response()

    try:
        payload = response.json(parse_float=Decimal, parse_int=Decimal)
    except (TypeError, ValueError) as exc:
        raise invalid_upstream_response() from exc

    if not isinstance(payload, dict):
        raise invalid_upstream_response()

    rates = payload.get("rates")
    raw_rate = rates.get(target) if isinstance(rates, dict) else None
    raw_rate_date = payload.get("date")
    if (
        not isinstance(rates, dict)
        or isinstance(raw_rate, bool)
        or not isinstance(raw_rate, (Decimal, int))
        or not isinstance(raw_rate_date, str)
    ):
        raise invalid_upstream_response()

    rate = Decimal(raw_rate)
    try:
        rate_date = date.fromisoformat(raw_rate_date)
    except ValueError as exc:
        raise invalid_upstream_response() from exc

    if not rate.is_finite() or rate <= 0 or rate_date > asked_date:
        raise invalid_upstream_response()

    _rate_cache[cache_key] = (rate, rate_date)
    return rate, rate_date


@app.get("/tools/convert")
async def convert(
    amount: Annotated[Decimal, Query()],
    from_: Annotated[str, Query(alias="from")],
    to: Annotated[str, Query()],
    asked_date: Annotated[date, Query(alias="date")],
) -> JSONResponse:
    """Convert an amount using the rate published for the requested date."""
    if not amount.is_finite() or amount <= 0:
        raise APIError(400, "invalid_amount", "Amount must be finite and positive.")

    if not all(
        len(code) == 3 and code.isascii() and code.isalpha()
        for code in (from_, to)
    ):
        raise APIError(
            400, "invalid_currency", "Currencies must be three-letter codes."
        )

    base = from_.upper()
    target = to.upper()
    if base == target:
        raise APIError(400, "same_currency", "Source and target currencies must differ.")

    if asked_date > date.today():
        raise APIError(400, "invalid_date", "The requested date cannot be in the future.")
    if asked_date < SERIES_START_DATE:
        raise APIError(
            404,
            "rate_unavailable",
            "Rates are unavailable before 1999-01-04.",
        )

    rate, rate_date = await fetch_historical_rate(base, target, asked_date)
    try:
        with localcontext() as context:
            context.prec = max(
                28, len(amount.as_tuple().digits) + len(rate.as_tuple().digits)
            )
            result = (amount * rate).quantize(
                RESULT_QUANTUM, rounding=ROUND_HALF_UP
            )
    except DecimalException as exc:
        raise APIError(
            400,
            "invalid_amount",
            "Amount is too large to convert safely.",
        ) from exc

    return JSONResponse(
        content=jsonable_encoder(
            {
                "amount": amount,
                "from": base,
                "to": target,
                "rate": rate,
                "result": result,
                "rate_date": rate_date.isoformat(),
                "asked_date": asked_date.isoformat(),
                "source": "ECB via frankfurter.dev",
            }
        )
    )
