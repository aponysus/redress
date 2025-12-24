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
use case. Future versions may add optional classification context (for example,
Retry-After hints) without expanding the class set.

Classifiers map exceptions → `ErrorClass`:

- `default_classifier` uses name/fields heuristics.
- `http_classifier` maps HTTP status codes (429→RATE_LIMIT, 5xx→SERVER_ERROR, 408→TRANSIENT, 401/403 → AUTH/PERMISSION).
- `sqlstate_classifier` maps SQLSTATE codes (40001/40P01→CONCURRENCY, HYT00/08xxx→TRANSIENT, 28xxx→AUTH).
- `pyodbc_classifier` (contrib) reuses SQLSTATE mapping for pyodbc-like errors.

Provide your own classifier when you need domain-specific logic; everything else stays the same.
