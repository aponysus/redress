# tests/test_fastapi_contrib.py

import asyncio

from redress.contrib import fastapi as fastapi_contrib
from redress.contrib.asgi import default_operation as asgi_default_operation
from redress.contrib.fastapi import default_operation, is_idempotent_request, retry_middleware


class _DummyUrl:
    def __init__(self, path: str) -> None:
        self.path = path


class _DummyRoute:
    def __init__(self, path: str | None = None, path_format: str | None = None) -> None:
        self.path = path
        self.path_format = path if path_format is None else path_format


class _DummyRequest:
    def __init__(
        self,
        method: str,
        path: str,
        route_path: str | None = None,
        route_path_format: str | None = None,
    ) -> None:
        self.method = method
        self.url = _DummyUrl(path)
        scope = {"path": path}
        if route_path is not None:
            scope["route"] = _DummyRoute(path=route_path, path_format=route_path_format)
        elif route_path_format is not None:
            scope["route"] = _DummyRoute(path=None, path_format=route_path_format)
        self.scope = scope

    async def body(self) -> bytes:
        return b""


class _FakePolicy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call(self, func, **kwargs):
        self.calls.append(kwargs)
        return await func()


def test_default_operation_uses_route_path() -> None:
    request = _DummyRequest("GET", "/items/123", route_path="/items/{item_id}")
    assert default_operation(request) == "GET /items/{item_id}"


def test_default_operation_falls_back_to_request_path() -> None:
    request = _DummyRequest("POST", "/items/123")
    assert default_operation(request) == "POST /items/123"


def test_default_operation_uses_route_path_format_when_path_missing() -> None:
    request = _DummyRequest(
        "GET", "/items/123", route_path=None, route_path_format="/items/{item_id}"
    )
    assert default_operation(request) == "GET /items/{item_id}"


def test_default_operation_matches_asgi_fallback_when_route_absent() -> None:
    request = _DummyRequest("POST", "/items/123")
    assert default_operation(request) == asgi_default_operation(request)


def test_is_idempotent_request() -> None:
    assert is_idempotent_request(_DummyRequest("GET", "/")) is True
    assert is_idempotent_request(_DummyRequest("POST", "/")) is False


def test_retry_middleware_calls_policy_with_operation() -> None:
    policy = _FakePolicy()
    request = _DummyRequest("GET", "/items/123", route_path="/items/{item_id}")
    middleware = retry_middleware(policy)

    async def call_next(_request: _DummyRequest) -> str:
        return "ok"

    result = asyncio.run(middleware(request, call_next))
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/{item_id}"}]


def test_retry_middleware_skip_if_bypasses_policy() -> None:
    policy = _FakePolicy()
    request = _DummyRequest("POST", "/items/123")
    middleware = retry_middleware(policy, skip_if=lambda req: req.method == "POST")

    async def call_next(_request: _DummyRequest) -> str:
        return "ok"

    result = asyncio.run(middleware(request, call_next))
    assert result == "ok"
    assert policy.calls == []


def test_retry_middleware_call_kwargs_provider() -> None:
    policy = _FakePolicy()
    request = _DummyRequest("GET", "/items/123")
    middleware = retry_middleware(
        policy,
        call_kwargs=lambda req: {"operation": f"{req.method} {req.url.path}", "tags": {"x": 1}},
    )

    async def call_next(_request: _DummyRequest) -> str:
        return "ok"

    asyncio.run(middleware(request, call_next))
    assert policy.calls == [{"operation": "GET /items/123", "tags": {"x": 1}}]


def test_fastapi_public_exports_stable() -> None:
    assert fastapi_contrib.__all__ == [
        "IDEMPOTENT_METHODS",
        "AsyncPolicyLike",
        "CallKwargsProvider",
        "CallNext",
        "OperationBuilder",
        "PolicyProvider",
        "RequestLike",
        "SkipPredicate",
        "default_operation",
        "is_idempotent_request",
        "retry_middleware",
    ]
