# Recipes & integrations

## HTTPX (sync)

- Snippet: `docs/snippets/httpx_sync_retry.py`
- Shows per-class strategies (tighter backoff for 429s) and metric hook logging.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_sync_retry.py`.

## requests (sync)

- Snippet: `docs/snippets/requests_retry.py`
- Uses `http_classifier` with requests and emits metrics.
- Run: `uv pip install requests` then `uv run python docs/snippets/requests_retry.py`.

## HTTPX (async)

- Snippet: `docs/snippets/httpx_async_retry.py`
- Same shape as sync, with `AsyncRetryPolicy` and `httpx.AsyncClient`.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_retry.py`.

## Async worker loop

- Snippet: `docs/snippets/async_worker_retry.py`
- Simulates a message worker with retries and metrics per message.
- Run: `uv run python docs/snippets/async_worker_retry.py`.

## Async Postgres (asyncpg)

- Snippet: `docs/snippets/asyncpg_retry.py`
- Uses `sqlstate_classifier` to map SQLSTATE codes and retries with asyncpg.
- Run: `uv pip install asyncpg` and set `ASYNC_PG_DSN`, then `uv run python docs/snippets/asyncpg_retry.py`.

## PyODBC + SQLSTATE classifier

- Snippet: `docs/snippets/pyodbc_classifier.py` provides a SQLSTATE→ErrorClass mapper (also available as `sqlstate_classifier` in `reflexio.extras`).
- Snippet: `docs/snippets/pyodbc_retry.py` shows batched row fetch under retry.
- Run: `uv pip install pyodbc` and set `PYODBC_CONN_STR`, then `uv run python docs/snippets/pyodbc_retry.py`.

## FastAPI proxy with retries

- Snippet: `docs/snippets/fastapi_downstream.py`
- Wraps a downstream call with retries and exposes `/metrics` counters.
- Run: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_downstream:app --reload`.

## FastAPI middleware with per-endpoint policies

- Snippet: `docs/snippets/fastapi_middleware.py`
- Middleware applies a retry policy to requests; includes a proxy endpoint.
- Run: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_middleware:app --reload`.

## Benchmarks (pyperf)

- Snippet: `docs/snippets/bench_retry.py`
- Measures bare sync retry overhead with pyperf runners.
- Run: `uv pip install .[dev]` then `uv run python docs/snippets/bench_retry.py`.
