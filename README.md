# FX conversion service

A small FastAPI service that converts currencies using ECB-backed historical
rates provided by Frankfurter.

## Setup

Python 3.10 or newer is recommended.

```sh
python -m venv .venv
# Activate .venv using the standard command for your shell.
python -m pip install -r requirements.txt
```

## Running

```sh
./run.sh
```

The service listens on `0.0.0.0:8080` by default. Configuration is read from:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `PORT` | `8080` | HTTP listening port |
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | Frankfurter-compatible upstream base URL |

`FX_UPSTREAM_BASE` makes the rate provider replaceable, including with a fake
upstream during testing.

## API

### `GET /tools/convert`

All query parameters are required:

| Parameter | Meaning |
| --------- | ------- |
| `amount` | Finite, positive decimal amount |
| `from` | Three-letter source currency code |
| `to` | Three-letter target currency code |
| `date` | Requested date in `YYYY-MM-DD` format |

Example:

```sh
curl "http://localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-30"
```

Representative response:

```json
{
  "amount": 250,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-30",
  "source": "ECB via frankfurter.dev"
}
```

## Date behavior

`asked_date` is the calendar date requested by the caller. `rate_date` is the
actual publication date returned by Frankfurter and is authoritative. For a
weekend or holiday, Frankfurter may return the previous published working-day
rate. The service accepts that rate while exposing its true date in
`rate_date`.

Historical requests never fall back to `/latest`. Future dates and dates before
the supported series start (`1999-01-04`) are rejected. A response whose
`rate_date` is later than `asked_date` is also rejected.

## Amount and currency behavior

- Amounts must be finite and greater than zero. Arbitrary practical decimal
  precision is accepted.
- Amounts and rates use `Decimal` arithmetic. The rate retains its full
  precision during multiplication; only the result is rounded to two decimal
  places using `ROUND_HALF_UP`.
- Currency codes are normalized to uppercase and must contain exactly three
  ASCII letters.
- The service does not maintain a hardcoded currency list. Syntactically valid
  but unsupported currencies are reported from the upstream response.
- Identical source and target currencies are rejected.

## Cache

Successfully validated rates are cached in process memory by upstream base,
source currency, target currency, and requested date. The amount is not part of
the key, so different amounts reuse the same rate. Failures are not cached. The
cache is intentionally process-local for this case.

## Errors

Failures return a non-2xx status with exactly this structure:

```json
{
  "error": "<machine_code>",
  "message": "<customer-safe message>"
}
```

| HTTP | Error code | Meaning |
| ---- | ---------- | ------- |
| 422 | `invalid_request` | Required parameters are missing or syntactically invalid |
| 400 | `invalid_amount` | Amount is non-positive, non-finite, or too extreme to calculate safely |
| 400 | `invalid_currency` | Currency syntax is invalid or the upstream rejects the currency |
| 400 | `same_currency` | Source and target currencies are identical |
| 400 | `invalid_date` | Requested date is in the future |
| 404 | `rate_unavailable` | Date is before the series or the upstream has no rate |
| 504 | `upstream_timeout` | Rate provider timed out |
| 502 | `upstream_unavailable` | Rate provider could not be reached or was unavailable |
| 502 | `upstream_invalid_response` | Rate provider returned an unusable response |
| 500 | `internal_error` | Unexpected application failure |

Customer responses do not expose raw upstream error details.

## Testing

```sh
./test.sh
```

The pytest suite is fully offline. It replaces upstream HTTP with
`httpx.MockTransport`, fails unexpected upstream calls, and clears the in-memory
cache between tests. Neither Frankfurter nor general network availability is
required.
