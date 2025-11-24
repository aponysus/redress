# Recipes & integrations

## HTTPX (sync)

- Snippet: `docs/snippets/httpx_sync_retry.py`
- Shows per-class strategies (tighter backoff for 429s) and metric hook logging.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_sync_retry.py`.

## HTTPX (async)

- Snippet: `docs/snippets/httpx_async_retry.py`
- Same shape as sync, with `AsyncRetryPolicy` and `httpx.AsyncClient`.
- Run: `uv pip install httpx` then `uv run python docs/snippets/httpx_async_retry.py`.

## Async worker loop

- Snippet: `docs/snippets/async_worker_retry.py`
- Simulates a message worker with retries and metrics per message.
- Run: `uv run python docs/snippets/async_worker_retry.py`.

## PyODBC + SQLSTATE classifier

- Snippet: `docs/snippets/pyodbc_classifier.py` provides a SQLSTATE→ErrorClass mapper (also available as `sqlstate_classifier` in `reflexio.extras`).
- Snippet: `docs/snippets/pyodbc_retry.py` shows batched row fetch under retry.
- Run: `uv pip install pyodbc` and set `PYODBC_CONN_STR`, then `uv run python docs/snippets/pyodbc_retry.py`.

## FastAPI proxy with retries

- Snippet: `docs/snippets/fastapi_downstream.py`
- Wraps a downstream call with retries and exposes `/metrics` counters.
- Run: `uv pip install "fastapi[standard]" httpx` then `uv run uvicorn docs.snippets.fastapi_downstream:app --reload`.
