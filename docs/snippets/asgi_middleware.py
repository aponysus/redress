"""
ASGI (Starlette-style) middleware integration using redress.contrib.asgi.

Run:
    uv pip install starlette "uvicorn[standard]"
    uv run uvicorn docs.snippets.asgi_middleware:app --reload

This shape also works in frameworks that accept Starlette-style middleware,
such as FastAPI and Litestar.
"""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from redress import AsyncRetryPolicy
from redress.contrib.asgi import default_operation, is_idempotent_request, retry_middleware
from redress.extras import http_classifier
from redress.strategies import decorrelated_jitter


def policy_for(_request: Request) -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=http_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        max_attempts=3,
        deadline_s=5.0,
    )


async def ok(_request: Request) -> Response:
    return JSONResponse({"ok": True})


async def create(_request: Request) -> Response:
    return JSONResponse({"created": True}, status_code=201)


app = Starlette(
    routes=[
        Route("/ok", ok, methods=["GET"]),
        Route("/items", create, methods=["POST"]),
    ]
)

app.middleware("http")(
    retry_middleware(
        policy_provider=policy_for,
        operation=default_operation,
        skip_if=lambda req: not is_idempotent_request(req),
    )
)
