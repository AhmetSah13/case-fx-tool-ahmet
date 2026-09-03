# Production review

## Findings

### 1. Historical rates can be wrong and assigned to the wrong date

**What is wrong:** The cache key contains only the currency pair, not the
requested date (lines 28–30). A rate fetched for one date is therefore reused
for every other date and relabeled with the new request's date. Outside the
cache, the function never reads the upstream payload's `date`; it always returns
the requested date or today (line 44). If a response lacks the target rate, it
also falls back to `/latest` (lines 36–40), even for a historical request.

**Customer impact:** An agent can quote the latest available rate for an old transaction, or
reuse one historical rate for another day, while confidently claiming that the
rate belongs to the requested date. This creates incorrect financial data with
misleading provenance, which is more dangerous than returning no result.

**How I would verify it:** Configure a fake upstream with different rates for
two dates, request both dates for the same pair, and assert that two upstream
calls occur and each response reports the payload's actual date. Separately,
return a Friday payload for a weekend request and confirm that Friday—not the
requested Sunday—is reported as the rate date.

### 2. Upstream failures become apparently successful zero conversions

**What is wrong:** The broad exception handler catches every failure and returns
a normal dictionary containing `rate: 0.0` and `result: 0.0` (lines 71–81).
FastAPI consequently sends HTTP 200. The upstream status is not checked before
JSON parsing, so timeouts, connection failures, error responses, non-JSON
bodies, and malformed payloads can all end in this false-success path.

**Customer impact:** A customer or agent cannot distinguish a real zero-valued
conversion from a provider outage or software error. It may present or persist
zero as a valid financial result instead of stopping and asking the customer to
retry.

**How I would verify it:** Make the fake client raise a timeout, then return an
HTTP 500, non-JSON text, and JSON without the requested rate. Each case should
produce a non-2xx status and a structured error; the current implementation
returns HTTP 200 with zeros.

### 3. The required public and runtime contracts are not honored

**What is wrong:** The upstream URL is hardcoded (line 18), so
`FX_UPSTREAM_BASE` is ignored. The route exposes `from_` and `on` (lines 48–49),
whereas callers are required to send `from` and `date`. Those required names can
be ignored as extra query parameters while the defaults select EUR and the
latest rate. Successful responses also omit `asked_date` (lines 62–70).

**Customer impact:** A correctly formed request can be calculated using the
wrong source currency and wrong date. Operators also cannot redirect traffic to
a controlled upstream during testing or an incident, and callers lack the field
needed to explain a weekend rate to a customer.

**How I would verify it:** Inspect the generated OpenAPI query names, then send
`from=USD&date=2024-01-10` to a fake upstream configured through the environment.
Record which host, base, and path are actually requested and inspect whether the
response includes `asked_date`.

### 4. Rounding and input handling can produce unsafe monetary results

**What is wrong:** The endpoint parses `amount` as a binary float and rounds the
rate to two decimals before multiplication (lines 48 and 60–61). It imposes no
policy for zero, negative, non-finite, or excessively precise amounts, and does
not reject identical currencies before contacting the upstream.

**Customer impact:** Premature rate rounding can materially change a conversion,
especially for large amounts, while invalid inputs can be accepted or collapse
into the false-success behavior above. The output may look precise to two
decimal places despite being calculated from a degraded rate.

**How I would verify it:** Return a rate of `1.2349` and convert `1000`; the code
uses `1.23` and returns `1230.00` rather than `1234.90`. Also exercise zero,
negative, NaN, Infinity, high-precision, and same-currency requests and require
explicit, documented outcomes.

## Fix before shipping

I would first fix the historical rate provenance and cache behavior in finding
1. It can silently provide both the wrong rate and a false date under an HTTP
200 response, leaving the customer no signal that the answer is unsafe. The fix
must key rates by currency pair and requested date, cache the actual upstream
date with the rate, and never replace a historical lookup with `/latest`.

## Suspicious but acceptable

Using a process-local dictionary as the cache (lines 20–21) is reasonable for a
small, single-process service and does not require Redis or a database. The
production defect is the information used in its key and value, not the choice
of an in-memory mechanism itself.
