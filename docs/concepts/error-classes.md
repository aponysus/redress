# Error classes & classifiers

`ErrorClass` is a coarse bucket so you can tune backoff without knowing every exception type.

Classes:

- `AUTH`, `PERMISSION` – do not retry.
- `PERMANENT` – user/config errors, no retry.
- `CONCURRENCY` – conflicts/deadlocks (e.g., SQLSTATE 40001/409).
- `RATE_LIMIT` – 429s, quotas.
- `SERVER_ERROR` – 5xx-style.
- `TRANSIENT` – timeouts, network hiccups.
- `UNKNOWN` – fallback when nothing else matches (capped via `max_unknown_attempts`).

Redress intentionally keeps `ErrorClass` small and fixed. The goal is semantic
classification ("rate limit" vs. "server error") rather than mechanical mapping to
every exception type. If you need finer-grained behavior, use separate policies per
use case. Optional classification context can carry hints (for example, Retry-After)
without expanding the class set.

Classifiers map exceptions → `ErrorClass` or `Classification`:

- `default_classifier` uses a best-effort sequence of marker types, status/code fields, and
  name-based heuristics.
- `strict_classifier` uses the same sequence but **skips name-based heuristics** for more
  predictable behavior.
- `http_classifier` maps HTTP status codes (429→RATE_LIMIT, 5xx→SERVER_ERROR, 408→TRANSIENT, 401/403 → AUTH/PERMISSION).
- `http_retry_after_classifier` behaves like `http_classifier` but populates `retry_after_s` when present.
- `sqlstate_classifier` maps SQLSTATE codes (40001/40P01→CONCURRENCY, HYT00/08xxx→TRANSIENT, 28xxx→AUTH).
- `pyodbc_classifier` (extras) reuses SQLSTATE mapping for pyodbc-like errors.

Default classifier precedence (first match wins):

1. Explicit redress marker types (PermanentError, RateLimitError, etc.).
2. Numeric `status` or `code` attributes.
3. Name-based heuristics (e.g., "timeout", "connection", "auth", "permission").
4. Fallback to `UNKNOWN`.

Name-based heuristics are convenient for quick starts but can surprise you if your exception
names are custom. For production systems, prefer explicit domain classifiers (HTTP/DB/etc.) or
`strict_classifier` with your own overrides.

## Classification context

Classifiers may also return a `Classification` instead of a plain `ErrorClass`. Returning
`ErrorClass` is shorthand for `Classification(klass=klass)`.
`details` is intended for low-risk string metadata and is not emitted as metric tags.
See `http_retry_after_classifier` for a built-in helper that extracts Retry-After hints.

```python
from redress import Classification, ErrorClass
from redress.strategies import BackoffContext

def classifier(exc: BaseException) -> Classification:
    return Classification(
        klass=ErrorClass.RATE_LIMIT,
        retry_after_s=2.0,
        details={"source": "header"},
    )

def strategy(ctx: BackoffContext) -> float:
    return float(ctx.classification.retry_after_s or 0.0)
```
