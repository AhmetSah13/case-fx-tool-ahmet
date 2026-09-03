# Notes

## Decisions

I kept the implementation in one application module because the case has one
endpoint and a short time budget. Additional controller, repository, or storage
layers would make the behavior harder to review without adding useful
separation.

The requested date and the rate's publication date are separate concepts. A
weekend or holiday request may legitimately receive the previous working day's
published rate, so the response preserves both `asked_date` and `rate_date`.
The upstream date is authoritative. Future dates, dates before 1999-01-04, and
responses dated after the request are rejected rather than guessed or replaced
with `/latest`.

Amounts and rates use `Decimal`. Multiplication uses the full upstream rate,
then the converted result is rounded to two decimal places with
`ROUND_HALF_UP`. This avoids changing the result by rounding the rate first.

The cache stores only successfully validated `(rate, rate_date)` values. Its key
contains the configured upstream, normalized currency pair, and requested date;
amount is excluded because it does not change the rate. A process-local
dictionary is enough for this case, and failures remain retryable because they
are not cached.

Timeouts, network failures, upstream statuses, and malformed payloads become
controlled, customer-safe errors. No failure is converted into a zero rate or
zero result.

## With another day

I would first add structured request and upstream-failure logging, with careful
redaction, so production incidents could be diagnosed without exposing details
to customers. Next I would bound the cache and define expiry behavior,
especially if current-day or latest rates were later supported. Metrics for
latency, error categories, and cache effectiveness would follow. If product
requirements called for it, currency support could also be checked through an
explicit upstream capability endpoint rather than inferred from conversion
responses.

## AI tools

I used Codex throughout the normal workflow: to audit the repository and brief,
assist with implementation, generate and check edge-case tests, and refine the
result after review. I reviewed decisions against the case requirements,
inspected generated changes, and verified behavior through offline tests and
the supplied shell entry points. AI output was treated as a draft to validate,
not as evidence that the code worked.

## One thing the AI got wrong

An early implementation serialized `Decimal` response fields as JSON strings.
That preserved decimal precision internally but did not match the API contract,
which expects numeric values for `amount`, `rate`, and `result`. A sanity check
caught the mismatch before the change was accepted. I adjusted the response
encoding, reran the conversion checks, and verified the actual JSON types.

It was a useful reminder that type-safe internal arithmetic does not
automatically guarantee the correct external API representation, and that AI
output still needs behavioral verification.
