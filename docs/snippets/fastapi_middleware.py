"""
FastAPI example with middleware applying per-endpoint retry policies.

Run:
    uv pip install "fastapi[standard]" httpx
    uv run uvicorn docs.snippets.fastapi_middleware:app --reload
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response

from redress import RetryPolicy
from redress.extras import http_classifier
from redress.strategies import decorrelated_jitter


def make_policy(operation: str) -> RetryPolicy:
    return RetryPolicy(
        classifier=http_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=4,
        deadline_s=8.0,
    )


app = FastAPI()


@app.middleware("http")
async def retry_middleware(request: Request, call_next) -> Response:
    operation = request.url.path
    policy = make_policy(operation)

    async def _call() -> Response:
        return await call_next(request)

    return await policy.call(_call, operation=operation)


@app.get("/ok")
async def ok() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/proxy")
async def proxy() -> dict[str, str]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get("https://httpbin.org/status/500")
        resp.raise_for_status()
        return {"body": resp.text}
