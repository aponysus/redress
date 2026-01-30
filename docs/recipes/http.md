# HTTP classifiers & Retry-After

This recipe shows two common patterns:

1) exception-based HTTP retries (raise for status)
2) result-based retries with Retry-After support

## Exception-based HTTP retries

Use `http_retry_after_classifier` when your HTTP client raises exceptions that carry
status/headers (e.g., httpx `HTTPStatusError`).

```python
import httpx
from redress import Policy, Retry
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or

policy = Policy(
    retry=Retry(
        classifier=http_retry_after_classifier,
        strategy=retry_after_or(decorrelated_jitter(max_s=5.0)),
        max_attempts=5,
        deadline_s=10.0,
    )
)


def fetch(url: str) -> httpx.Response:
    with httpx.Client(timeout=3.0) as client:
        resp = client.get(url)
        resp.raise_for_status()  # raises for 4xx/5xx
        return resp

response = policy.call(lambda: fetch("https://httpbin.org/status/429"), operation="http_fetch")
```

## Result-based HTTP retries (no exceptions)

Use `result_classifier` when you want to inspect responses without raising.
This also lets you attach Retry-After metadata explicitly.

```python
import httpx
from redress import Classification, ErrorClass, Policy, Retry
from redress.strategies import decorrelated_jitter, retry_after_or


def classify_result(resp: httpx.Response) -> ErrorClass | Classification | None:
    if resp.status_code == 429:
        return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=1.0)
    if resp.status_code >= 500:
        return ErrorClass.SERVER_ERROR
    return None

policy = Policy(
    retry=Retry(
        classifier=lambda exc: ErrorClass.UNKNOWN,
        result_classifier=classify_result,
        strategy=retry_after_or(decorrelated_jitter(max_s=3.0)),
        max_attempts=5,
        deadline_s=8.0,
    )
)

with httpx.Client(timeout=3.0) as client:
    response = policy.call(lambda: client.get("https://httpbin.org/status/503"))
```

## Adding a circuit breaker

Circuit breakers use the same classification that drives retries. This example
trips the breaker on repeated server errors.

```python
import httpx
from redress import CircuitBreaker, ErrorClass, Policy, Retry, default_classifier
from redress.strategies import decorrelated_jitter

breaker = CircuitBreaker(
    failure_threshold=3,
    window_s=30.0,
    recovery_timeout_s=10.0,
    trip_on={ErrorClass.SERVER_ERROR},
)

policy = Policy(
    retry=Retry(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=3,
        deadline_s=6.0,
    ),
    circuit_breaker=breaker,
)

def fetch(url: str) -> httpx.Response:
    with httpx.Client(timeout=3.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp

response = policy.call(lambda: fetch("https://httpbin.org/status/500"), operation="http_fetch")
```
