# tests/test_httpx_contrib.py

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest

from redress import AsyncRetryPolicy, RetryPolicy, default_classifier
from redress.classify import Classification
from redress.contrib.httpx import (
    AsyncRetryingHttpxClient,
    RetryingHttpxClient,
    arequest_with_retry,
    default_operation,
    default_result_classifier,
    is_idempotent_method,
    request_with_retry,
)
from redress.errors import ErrorClass
from redress.strategies import retry_after_or


class _DummyUrl:
    def __init__(self, path: str) -> None:
        self.path = path


class _DummyResponse:
    def __init__(self, status_code: int, headers: object | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class _FakeSyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, dict[str, Any]]] = []

    def request(self, method: str, url: object, **kwargs: Any) -> str:
        self.calls.append((method, url, kwargs))
        return "ok"


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, dict[str, Any]]] = []

    async def request(self, method: str, url: object, **kwargs: Any) -> str:
        self.calls.append((method, url, kwargs))
        return "ok"


class _FakeSyncPolicy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, func, **kwargs):
        self.calls.append(kwargs)
        return func()


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


def test_request_with_retry_uses_policy_call_and_default_operation() -> None:
    client = _FakeSyncClient()
    policy = _FakeSyncPolicy()
    result = request_with_retry(
        client,
        policy,
        "get",
        "https://example.test/items/123?debug=1",
        timeout=1.5,
    )
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/123"}]
    assert client.calls == [("get", "https://example.test/items/123?debug=1", {"timeout": 1.5})]


def test_request_with_retry_skip_if_bypasses_policy() -> None:
    client = _FakeSyncClient()
    policy = _FakeSyncPolicy()
    result = request_with_retry(
        client,
        policy,
        "post",
        "/write",
        skip_if=lambda method, _url: method == "POST",
    )
    assert result == "ok"
    assert policy.calls == []
    assert client.calls == [("post", "/write", {})]


def test_request_with_retry_call_kwargs_override_operation() -> None:
    client = _FakeSyncClient()
    policy = _FakeSyncPolicy()
    request_with_retry(
        client,
        policy,
        "get",
        "/x",
        call_kwargs=lambda _method, _url: {"operation": "custom_op", "on_log": object()},
    )
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "custom_op"
    assert "on_log" in policy.calls[0]


def test_arequest_with_retry_uses_async_policy_call() -> None:
    client = _FakeAsyncClient()
    policy = _FakeAsyncPolicy()

    async def run() -> str:
        return await arequest_with_retry(client, policy, "GET", "/items/1")

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert client.calls == [("GET", "/items/1", {})]


def test_retrying_httpx_client_uses_defaults() -> None:
    client = _FakeSyncClient()
    policy = _FakeSyncPolicy()
    wrapped = RetryingHttpxClient(
        client,
        policy,
        skip_if=lambda method, _url: method == "POST",
    )

    result = wrapped.get("/items/1", timeout=2.0)
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert client.calls == [("GET", "/items/1", {"timeout": 2.0})]


def test_retrying_httpx_client_per_call_override() -> None:
    client = _FakeSyncClient()
    policy = _FakeSyncPolicy()
    wrapped = RetryingHttpxClient(client, policy, operation="global_op")

    wrapped.request("GET", "/x", operation="per_call_op")
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "per_call_op"


def test_async_retrying_httpx_client_uses_defaults() -> None:
    client = _FakeAsyncClient()
    policy = _FakeAsyncPolicy()
    wrapped = AsyncRetryingHttpxClient(client, policy)

    async def run() -> str:
        return await wrapped.get("/items/1")

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert client.calls == [("GET", "/items/1", {})]


def test_httpx_sync_smoke_retries_until_success() -> None:
    httpx = pytest.importorskip("httpx")
    attempts = {"count": 0}

    def handler(request: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, text="ok")

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=lambda _ctx: 0.0,
        max_attempts=4,
        deadline_s=1.0,
    )

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test") as client:
        wrapped = RetryingHttpxClient(client, policy)
        response = wrapped.get("/flaky")

    assert response.status_code == 200
    assert attempts["count"] == 3


def test_httpx_async_smoke_retries_until_success() -> None:
    httpx = pytest.importorskip("httpx")
    attempts = {"count": 0}

    def handler(request: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, request=request, text="ok")

    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=retry_after_or(lambda _ctx: 0.0, jitter_s=0.0),
        max_attempts=4,
        deadline_s=1.0,
    )

    async def run() -> Any:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://example.test"
        ) as client:
            wrapped = AsyncRetryingHttpxClient(client, policy)
            return await wrapped.get("/rate-limited")

    response = asyncio.run(run())
    assert response.status_code == 200
    assert attempts["count"] == 3
