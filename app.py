"""FastAPI application for the FX conversion tool."""

import os
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

import httpx
from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


DEFAULT_FX_UPSTREAM_BASE = "https://api.frankfurter.dev"
FX_UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", DEFAULT_FX_UPSTREAM_BASE).rstrip("/")
HTTP_TIMEOUT_SECONDS = 5.0
RESULT_QUANTUM = Decimal("0.01")

app = FastAPI(title="FX conversion tool")


async def fetch_historical_rate(
    base: str, target: str, asked_date: date
) -> tuple[Decimal, date]:
    """Fetch a historical rate and the publication date reported upstream."""
    url = f"{FX_UPSTREAM_BASE}/v1/{asked_date.isoformat()}"
    params = {"base": base, "symbols": target}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()

    payload = response.json(parse_float=Decimal)
    rate = Decimal(str(payload["rates"][target]))
    rate_date = date.fromisoformat(payload["date"])
    return rate, rate_date


@app.get("/tools/convert")
async def convert(
    amount: Annotated[Decimal, Query(gt=0)],
    from_: Annotated[
        str, Query(alias="from", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    ],
    to: Annotated[str, Query(min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")],
    asked_date: Annotated[date, Query(alias="date")],
) -> JSONResponse:
    """Convert an amount using the rate published for the requested date."""
    base = from_.upper()
    target = to.upper()
    rate, rate_date = await fetch_historical_rate(base, target, asked_date)
    result = (amount * rate).quantize(RESULT_QUANTUM, rounding=ROUND_HALF_UP)

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
