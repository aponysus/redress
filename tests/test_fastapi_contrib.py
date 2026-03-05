# tests/test_fastapi_contrib.py

import asyncio

from redress.contrib.fastapi import default_operation, is_idempotent_request, retry_middleware


class _DummyUrl:
    def __init__(self, path: str) -> None:
        self.path = path


class _DummyRoute:
    def __init__(self, path: str) -> None:
        self.path = path
        self.path_format = path


class _DummyRequest:
    def __init__(self, method: str, path: str, route_path: str | None = None) -> None:
        self.method = method
        self.url = _DummyUrl(path)
        scope = {"path": path}
        if route_path is not None:
            scope["route"] = _DummyRoute(route_path)
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
