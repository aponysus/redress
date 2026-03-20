# Examples & integrations

## HTTPX contrib wrappers (sync + async)

- Snippet: `docs/snippets/httpx_contrib.py`
- Canonical helper API via `RetryingHttpxClient` / `AsyncRetryingHttpxClient`.
- Includes `default_result_classifier` and idempotency gating.
- Run: `uv pip install "redress[httpx]"` then `uv run python docs/snippets/httpx_contrib.py`.

## HTTPX (sync)

- Snippet: `docs/snippets/httpx_sync_retry.py`
- Shows per-class strategies (tighter backoff for 429s) and metric hook logging.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_sync_retry.py`.

## HTTPX Retry-After (sync)

- Snippet: `docs/snippets/httpx_retry_after.py`
- Uses result-based retries with Retry-After metadata and a fallback jitter strategy.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_retry_after.py`.

## requests (sync)

- Snippet: `docs/snippets/requests_retry.py`
- Uses `http_classifier` with requests and emits metrics.
- Run: `uv pip install requests` then `uv run python docs/snippets/requests_retry.py`.

## Prometheus contrib hook

- Snippet: `docs/snippets/prometheus_contrib.py`
- Uses `redress.contrib.prometheus.prometheus_hooks` with event and retry-sleep metrics.
- Run: `uv pip install "redress[prometheus]"` then `uv run python docs/snippets/prometheus_contrib.py`.

## Datadog contrib hook

- Snippet: `docs/snippets/datadog_contrib.py`
- Uses `redress.contrib.datadog.datadog_hooks` to emit DogStatsD counters and retry-delay histograms.
- Run: `uv pip install "redress[datadog]"` then `uv run python docs/snippets/datadog_contrib.py`.

## Sentry contrib hook

- Snippet: `docs/snippets/sentry_contrib.py`
- Uses `redress.contrib.sentry.sentry_hooks` to record breadcrumbs and terminal failure messages.
- Run: `uv pip install "redress[sentry]"` then `uv run python docs/snippets/sentry_contrib.py`.

## HTTPX (async)

- Snippet: `docs/snippets/httpx_async_retry.py`
- Same shape as sync, with `AsyncRetryPolicy` and `httpx.AsyncClient`.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_retry.py`.

## HTTPX async + Policy + circuit breaker

- Snippet: `docs/snippets/httpx_async_policy_breaker.py`
- Unified `AsyncPolicy` demo with Retry-After result retries and circuit breaking.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_policy_breaker.py`.

## Async worker loop

- Snippet: `docs/snippets/async_worker_retry.py`
- Simulates a message worker with retries and metrics per message.
- Run: `uv run python docs/snippets/async_worker_retry.py`.

## Async worker with cooperative abort

- Snippet: `docs/snippets/async_worker_abort.py`
- Shows `abort_if` for shutdown and `on_log` for durable attempt logging.
- Run: `uv run python docs/snippets/async_worker_abort.py`.

## Async Postgres (asyncpg)

- Snippet: `docs/snippets/asyncpg_retry.py`
- Uses `sqlstate_classifier` to map SQLSTATE codes and retries with asyncpg.
- Run: `uv pip install asyncpg` and set `ASYNC_PG_DSN`, then `uv run python docs/snippets/asyncpg_retry.py`.

## PyODBC + SQLSTATE classifier

- Classifier: `pyodbc_classifier` (in `redress.extras`) maps SQLSTATE codes to ErrorClass.
- Snippet: `docs/snippets/pyodbc_retry.py` shows batched row fetch under retry.
- Run: `uv pip install pyodbc` and set `PYODBC_CONN_STR`, then `uv run python docs/snippets/pyodbc_retry.py`.

## ASGI middleware (Starlette-style)

- Snippet: `docs/snippets/asgi_middleware.py`
- Uses `redress.contrib.asgi.retry_middleware` with `default_operation` (`METHOD + scope["path"]`).
- Scope: Starlette-style `(request, call_next)` middleware. This is not raw ASGI `(scope, receive, send)`.
- Run: `uv pip install starlette "uvicorn[standard]"` then `uv run uvicorn docs.snippets.asgi_middleware:app --reload`.

## gRPC unary-unary client interceptor

- Snippet: `docs/snippets/grpc_interceptor.py`
- Uses `redress.contrib.grpc.unary_unary_client_interceptor` and `aio_unary_unary_client_interceptor`.
- Recommended classifier: `redress.extras.grpc_classifier`.
- Run: `uv pip install "redress[grpc]"`.

## FastAPI proxy with retries

- Snippet: `docs/snippets/fastapi_downstream.py`
- Wraps a downstream call with retries and exposes `/metrics` counters.
- Run: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_downstream:app --reload`.
- Shape:

```python
from fastapi import FastAPI, HTTPException
from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

app = FastAPI()
policy = RetryPolicy(classifier=default_classifier, strategy=decorrelated_jitter(max_s=2.0))

@app.get("/proxy")
def proxy():
    def _call():
        resp = httpx.get("https://httpbin.org/status/500", timeout=3.0)
        resp.raise_for_status()
        return resp.text
    try:
        return {"body": policy.call(_call, operation="proxy_downstream")}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
```

## FastAPI middleware with per-endpoint policies

- Snippet: `docs/snippets/fastapi_middleware.py`
- Middleware applies a retry policy to requests; includes a proxy endpoint.
- Note: This retries the full handler; use only for idempotent endpoints.
- Run: `uv pip install "redress[fastapi]" "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_middleware:app --reload`.
- Shape:

```python
from fastapi import FastAPI, Request
from redress import AsyncRetryPolicy
from redress.contrib.fastapi import default_operation, retry_middleware
from redress.extras import http_classifier
from redress.strategies import decorrelated_jitter

app = FastAPI()

def policy_for(_request: Request) -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=http_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=4,
        deadline_s=8.0,
    )

app.middleware("http")(
    retry_middleware(
        policy_provider=policy_for,
        operation=default_operation,
    )
)
```

## Benchmarks (pyperf)

- Snippet: `docs/snippets/bench_retry.py`
- Measures bare sync retry overhead with pyperf runners.
- Run: `uv pip install .[dev]` then `uv run python docs/snippets/bench_retry.py`.
