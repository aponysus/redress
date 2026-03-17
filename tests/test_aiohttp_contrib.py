# tests/test_aiohttp_contrib.py

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from redress import AsyncRetryPolicy, default_classifier
from redress.classify import Classification
from redress.contrib import aiohttp as aiohttp_contrib
from redress.contrib.aiohttp import (
    AsyncRetryingAiohttpSession,
    arequest_with_retry,
    default_operation,
    default_result_classifier,
    is_idempotent_method,
)
from redress.errors import ErrorClass
from redress.strategies import retry_after_or


class _DummyUrl:
    def __init__(self, path: str) -> None:
        self.path = path


class _DummyResponse:
    def __init__(self, status: int, headers: object | None = None) -> None:
        self.status = status
        self.headers = headers or {}


class _HeaderProxy:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, key: str) -> str | None:
        return self._values.get(key)


class _FakeAsyncSession:
    def __init__(self, handler=None) -> None:
        self.calls: list[tuple[str, object, dict[str, Any]]] = []
        self.handler = handler

    async def request(self, method: str, url: object, **kwargs: Any) -> object:
        self.calls.append((method, url, kwargs))
        if self.handler is None:
            return "ok"
        return self.handler(method, url, kwargs)


class _FakeManagedAsyncSession(_FakeAsyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.entered = False
        self.exited = False

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> "_FakeManagedAsyncSession":
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited = True


class _FakeCloseOnlySession(_FakeAsyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeExitSession(_FakeAsyncSession):
    def __init__(self, exit_result: object) -> None:
        super().__init__()
        self.exit_result = exit_result

    async def __aexit__(self, exc_type, exc, tb) -> object:
        return self.exit_result


class _FakeAsyncPolicy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call(self, func, **kwargs):
        self.calls.append(kwargs)
        return await func()


def test_is_idempotent_method() -> None:
    assert is_idempotent_method("GET") is True
    assert is_idempotent_method("put") is True
    assert is_idempotent_method("POST") is False


def test_default_operation_from_url_attr() -> None:
    assert default_operation("get", _DummyUrl("/items/123")) == "GET /items/123"


def test_default_operation_from_url_string_strips_query() -> None:
    assert default_operation("post", "https://example.test/items/123?q=abc") == "POST /items/123"


def test_default_operation_handles_empty_and_relative_urls() -> None:
    assert default_operation("get", "") == "GET /"
    assert default_operation("get", "items/123") == "GET /items/123"
    assert default_operation("get", "https://example.test") == "GET /"


def test_default_result_classifier_rate_limit_retry_after_seconds() -> None:
    result = default_result_classifier(_DummyResponse(429, {"Retry-After": "2"}))
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 2.0


def test_default_result_classifier_rate_limit_retry_after_http_date() -> None:
    retry_after = format_datetime(datetime.now(UTC) + timedelta(seconds=5))
    result = default_result_classifier(_DummyResponse(429, {"Retry-After": retry_after}))
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s is not None
    assert result.retry_after_s >= 0.0


def test_default_result_classifier_mappings() -> None:
    assert default_result_classifier(_DummyResponse(503)) is ErrorClass.SERVER_ERROR
    assert default_result_classifier(_DummyResponse(408)) is ErrorClass.TRANSIENT
    assert default_result_classifier(_DummyResponse(409)) is ErrorClass.CONCURRENCY
    assert default_result_classifier(_DummyResponse(404)) is None


def test_default_result_classifier_handles_header_proxy_and_missing_retry_after() -> None:
    result = default_result_classifier(_DummyResponse(429, _HeaderProxy({"retry-after": "3"})))
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 3.0
    assert default_result_classifier(_DummyResponse(429)) is ErrorClass.RATE_LIMIT


def test_arequest_with_retry_uses_async_policy_call() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()

    async def run() -> object:
        return await arequest_with_retry(session, policy, "GET", "/items/1", timeout=1.5)

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert session.calls == [("GET", "/items/1", {"timeout": 1.5})]


def test_arequest_with_retry_skip_if_bypasses_policy() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()

    async def run() -> object:
        return await arequest_with_retry(
            session,
            policy,
            "post",
            "/write",
            skip_if=lambda method, _url: method == "POST",
        )

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == []
    assert session.calls == [("post", "/write", {})]


def test_arequest_with_retry_call_kwargs_override_operation() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()

    async def run() -> object:
        return await arequest_with_retry(
            session,
            policy,
            "GET",
            "/x",
            call_kwargs=lambda _method, _url: {"operation": "custom_op", "on_log": object()},
        )

    asyncio.run(run())
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "custom_op"
    assert "on_log" in policy.calls[0]


def test_arequest_with_retry_accepts_mapping_call_kwargs() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()

    async def run() -> object:
        return await arequest_with_retry(
            session,
            policy,
            "GET",
            "/mapped",
            call_kwargs={"tags": {"x": 1}},
        )

    asyncio.run(run())
    assert policy.calls == [{"operation": "GET /mapped", "tags": {"x": 1}}]


def test_async_retrying_aiohttp_session_uses_defaults() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)

    async def run() -> object:
        return await wrapped.get("/items/1")

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert session.calls == [("GET", "/items/1", {})]


def test_async_retrying_aiohttp_session_per_call_override() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy, operation="global_op")

    async def run() -> object:
        return await wrapped.request("GET", "/x", operation="per_call_op")

    asyncio.run(run())
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "per_call_op"


def test_async_retrying_aiohttp_session_context_manager_and_close_delegate() -> None:
    session = _FakeManagedAsyncSession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)

    async def run() -> None:
        async with wrapped:
            pass
        await wrapped.aclose()

    asyncio.run(run())
    assert session.entered is True
    assert session.exited is True
    assert session.closed is True


def test_async_retrying_aiohttp_session_method_helpers() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)

    async def run() -> None:
        await wrapped.post("/post")
        await wrapped.put("/put")
        await wrapped.patch("/patch")
        await wrapped.delete("/delete")
        await wrapped.head("/head")
        await wrapped.options("/options")

    asyncio.run(run())
    assert [call[:2] for call in session.calls] == [
        ("POST", "/post"),
        ("PUT", "/put"),
        ("PATCH", "/patch"),
        ("DELETE", "/delete"),
        ("HEAD", "/head"),
        ("OPTIONS", "/options"),
    ]


def test_async_retrying_aiohttp_session_aclose_noop_without_close() -> None:
    session = _FakeAsyncSession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)
    asyncio.run(wrapped.aclose())


def test_async_retrying_aiohttp_session_aexit_falls_back_to_close() -> None:
    session = _FakeCloseOnlySession()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)

    result = asyncio.run(wrapped.__aexit__(None, None, None))
    assert result is None
    assert session.closed is True


def test_async_retrying_aiohttp_session_aexit_normalizes_truthy_result() -> None:
    session = _FakeExitSession(1)
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingAiohttpSession(session, policy)

    result = asyncio.run(wrapped.__aexit__(None, None, None))
    assert result is True


def test_aiohttp_async_smoke_retries_until_success() -> None:
    attempts = {"count": 0}

    def handler(_method: str, _url: object, _kwargs: dict[str, Any]) -> _DummyResponse:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _DummyResponse(429, {"Retry-After": "0"})
        return _DummyResponse(200)

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=retry_after_or(lambda _ctx: 0.0, jitter_s=0.0),
        max_attempts=4,
        deadline_s=1.0,
    )

    async def run() -> object:
        session = _FakeAsyncSession(handler=handler)
        wrapped = AsyncRetryingAiohttpSession(session, policy)
        return await wrapped.get("/rate-limited")

    response = asyncio.run(run())
    assert isinstance(response, _DummyResponse)
    assert response.status == 200
    assert attempts["count"] == 3


def test_aiohttp_public_exports_stable() -> None:
    assert aiohttp_contrib.__all__ == [
        "AsyncClientSessionLike",
        "AsyncPolicyLike",
        "AsyncRetryingAiohttpSession",
        "CallKwargsProvider",
        "IDEMPOTENT_METHODS",
        "OperationBuilder",
        "RequestPredicate",
        "ResponseLike",
        "arequest_with_retry",
        "default_operation",
        "default_result_classifier",
        "is_idempotent_method",
    ]
