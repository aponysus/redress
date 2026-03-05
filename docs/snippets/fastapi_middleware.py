"""
FastAPI example with middleware applying per-endpoint retry policies.

Run:
    uv pip install "redress[fastapi]" "fastapi[standard]" httpx
    uv run uvicorn docs.snippets.fastapi_middleware:app --reload
"""

import httpx
from fastapi import FastAPI, Request

from redress import AsyncRetryPolicy
from redress.contrib.fastapi import default_operation, retry_middleware
from redress.extras import http_classifier
from redress.strategies import decorrelated_jitter


def policy_for(_request: Request) -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=http_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        max_attempts=4,
        deadline_s=8.0,
    )


app = FastAPI()

app.middleware("http")(
    retry_middleware(
        policy_provider=policy_for,
        operation=default_operation,
    )
)


@app.get("/ok")
async def ok() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/proxy")
async def proxy() -> dict[str, str]:
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get("https://httpbin.org/status/500")
        resp.raise_for_status()
        return {"body": resp.text}
