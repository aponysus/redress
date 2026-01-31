# Classification & classifier authoring

Classification is the core of redress. A classifier maps a failure into a small, fixed
`ErrorClass` (or a richer `Classification`), and that classification drives retries,
backoff, limits, and circuit breaker decisions.

## How classifier selection works

- **Exception path**: if the call raises, the policy's `classifier` runs.
  - It can return `ErrorClass` or `Classification`; redress normalizes `ErrorClass`
    into `Classification(klass=...)`.
- **Result path**: if the call returns successfully and `result_classifier` is set,
  it runs on the returned value.
  - If it returns `None`, the result is treated as success.
  - If it returns `ErrorClass` or `Classification`, the result is treated as a failure
    and retried according to policy.

Use `result_classifier` when you want to retry on return values (HTTP responses,
status codes, etc.) without raising exceptions.

## Classification fields

`Classification` carries the error class plus optional hints:

```python
@dataclass(frozen=True)
class Classification:
    klass: ErrorClass
    retry_after_s: float | None = None
    details: Mapping[str, str] = field(default_factory=dict)
```

## Built-in classifiers

Core:
- `default_classifier` – best-effort mapping (includes name heuristics).
- `strict_classifier` – same logic without name heuristics.

Extras (`redress.extras`):
- `http_classifier`, `http_retry_after_classifier`
- `sqlstate_classifier`, `pyodbc_classifier`
- `urllib3_classifier`, `redis_classifier`, `aiohttp_classifier`, `grpc_classifier`, `boto3_classifier`

## Writing a safe classifier

Guidelines:

- **Classify on stable attributes**: HTTP status codes, SQLSTATE, error type.
- **Prefer type checks** over string parsing.
- **Avoid I/O** or slow operations; classifiers are on the hot path.
- **Be defensive**: missing attributes should not raise.
- **Return UNKNOWN** when unsure; let policy caps handle it.
- **Keep it deterministic**: no randomness, no time-based behavior.

A minimal classifier template:

```python
from redress import ErrorClass


def my_classifier(exc: BaseException) -> ErrorClass:
    if isinstance(exc, TimeoutError):
        return ErrorClass.TRANSIENT
    if getattr(exc, "status", None) == 429:
        return ErrorClass.RATE_LIMIT
    return ErrorClass.UNKNOWN
```

## Pitfalls to avoid

- **Brittle string heuristics**: class names or error messages change across versions.
- **High-cardinality tagging** in hooks: avoid logging full URLs, user IDs, or raw SQL.
- **Over-classifying unknown errors**: prefer `UNKNOWN` and cap with `max_unknown_attempts`.

For practical patterns and copy/paste examples, see:

- [HTTP recipes](../recipes/http.md)
- [DB recipes](../recipes/db.md)
- [Observability recipes](../recipes/observability.md)
