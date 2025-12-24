"""
FastAPI service that proxies a downstream call with redress.

Run locally with:
    uv run uvicorn examples.fastapi_downstream:app --reload
"""

import httpx
from fastapi import FastAPI, HTTPException

from redress import RetryPolicy, default_classifier
from redress.strategies import decorrelated_jitter

DOWNSTREAM_URL = "https://httpbin.org/status/500"

app = FastAPI()

metrics: dict[str, int] = {"retry": 0, "success": 0, "permanent_fail": 0}


def on_metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
    metrics[event] = metrics.get(event, 0) + 1


policy = RetryPolicy(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=2.0),
    deadline_s=5.0,
    max_attempts=4,
)


@app.get("/proxy")
def proxy() -> dict[str, str]:
    """
    Proxy a flaky downstream endpoint with retries applied.
    """

    def _call() -> str:
        response = httpx.get(DOWNSTREAM_URL, timeout=3.0)
        response.raise_for_status()
        return response.text

    try:
        body = policy.call(_call, on_metric=on_metric, operation="proxy_downstream")
        return {"body": body}
    except Exception as exc:  # noqa: BLE001 - demo service
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/metrics")
def get_metrics() -> dict[str, int]:
    return metrics
