# tests/test_requests_contrib.py

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from redress import RetryPolicy, default_classifier
from redress.classify import Classification
from redress.contrib import requests as requests_contrib
from redress.contrib.requests import (
    RetryingRequestsSession,
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


class _HeaderProxy:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, key: str) -> str | None:
        return self._values.get(key)


class _FakeSyncSession:
    def __init__(self, handler=None) -> None:
        self.calls: list[tuple[str, object, dict[str, Any]]] = []
        self.handler = handler

    def request(self, method: str, url: object, **kwargs: Any) -> object:
        self.calls.append((method, url, kwargs))
        if self.handler is None:
            return "ok"
        return self.handler(method, url, kwargs)


class _FakeManagedSyncSession(_FakeSyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False
        self.entered = False
        self.exited = False

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeManagedSyncSession":
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exited = True


class _FakeCloseOnlySyncSession(_FakeSyncSession):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeExitSession(_FakeSyncSession):
    def __init__(self, exit_result: object) -> None:
        super().__init__()
        self.exit_result = exit_result

    def __exit__(self, exc_type, exc, tb) -> object:
        return self.exit_result


class _FakeAsyncCloseSession(_FakeSyncSession):
    async def close(self) -> None:
        return None


class _FakeSyncPolicy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, func, **kwargs):
        self.calls.append(kwargs)
        return func()


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


def test_request_with_retry_uses_policy_call_and_default_operation() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    result = request_with_retry(
        session,
        policy,
        "get",
        "https://example.test/items/123?debug=1",
        timeout=1.5,
    )
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/123"}]
    assert session.calls == [("get", "https://example.test/items/123?debug=1", {"timeout": 1.5})]


def test_request_with_retry_skip_if_bypasses_policy() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    result = request_with_retry(
        session,
        policy,
        "post",
        "/write",
        skip_if=lambda method, _url: method == "POST",
    )
    assert result == "ok"
    assert policy.calls == []
    assert session.calls == [("post", "/write", {})]


def test_request_with_retry_call_kwargs_override_operation() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    request_with_retry(
        session,
        policy,
        "get",
        "/x",
        call_kwargs=lambda _method, _url: {"operation": "custom_op", "on_log": object()},
    )
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "custom_op"
    assert "on_log" in policy.calls[0]


def test_request_with_retry_accepts_mapping_call_kwargs() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    request_with_retry(
        session,
        policy,
        "GET",
        "/mapped",
        call_kwargs={"tags": {"x": 1}},
    )
    assert policy.calls == [{"operation": "GET /mapped", "tags": {"x": 1}}]


def test_retrying_requests_session_uses_defaults() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    result = wrapped.get("/items/1")
    assert result == "ok"
    assert policy.calls == [{"operation": "GET /items/1"}]
    assert session.calls == [("GET", "/items/1", {})]


def test_retrying_requests_session_per_call_override() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy, operation="global_op")

    wrapped.request("GET", "/x", operation="per_call_op")
    assert len(policy.calls) == 1
    assert policy.calls[0]["operation"] == "per_call_op"


def test_retrying_requests_session_method_helpers() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    wrapped.post("/post")
    wrapped.put("/put")
    wrapped.patch("/patch")
    wrapped.delete("/delete")
    wrapped.head("/head")
    wrapped.options("/options")

    assert [call[:2] for call in session.calls] == [
        ("POST", "/post"),
        ("PUT", "/put"),
        ("PATCH", "/patch"),
        ("DELETE", "/delete"),
        ("HEAD", "/head"),
        ("OPTIONS", "/options"),
    ]


def test_retrying_requests_session_context_manager_and_close_delegate() -> None:
    session = _FakeManagedSyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    with wrapped:
        pass
    wrapped.close()

    assert session.entered is True
    assert session.exited is True
    assert session.closed is True


def test_retrying_requests_session_close_noop_without_close() -> None:
    session = _FakeSyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)
    wrapped.close()


def test_retrying_requests_session_exit_falls_back_to_close() -> None:
    session = _FakeCloseOnlySyncSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    result = wrapped.__exit__(None, None, None)
    assert result is None
    assert session.closed is True


def test_retrying_requests_session_exit_normalizes_truthy_result() -> None:
    session = _FakeExitSession(1)
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    result = wrapped.__exit__(None, None, None)
    assert result is True


def test_retrying_requests_session_rejects_async_close() -> None:
    session = _FakeAsyncCloseSession()
    policy = _FakeSyncPolicy()
    wrapped = RetryingRequestsSession(session, policy)

    try:
        wrapped.close()
    except TypeError as exc:
        assert "synchronous close method" in str(exc)
    else:
        raise AssertionError("expected TypeError")


def test_requests_sync_smoke_retries_until_success() -> None:
    attempts = {"count": 0}

    def handler(_method: str, _url: object, _kwargs: dict[str, Any]) -> _DummyResponse:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _DummyResponse(429, {"Retry-After": "0"})
        return _DummyResponse(200)

    policy = RetryPolicy(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=retry_after_or(lambda _ctx: 0.0, jitter_s=0.0),
        max_attempts=4,
        deadline_s=1.0,
    )

    session = _FakeSyncSession(handler=handler)
    wrapped = RetryingRequestsSession(session, policy)
    response = wrapped.get("/rate-limited")

    assert isinstance(response, _DummyResponse)
    assert response.status_code == 200
    assert attempts["count"] == 3


def test_requests_public_exports_stable() -> None:
    assert requests_contrib.__all__ == [
        "CallKwargsProvider",
        "IDEMPOTENT_METHODS",
        "OperationBuilder",
        "RequestPredicate",
        "ResponseLike",
        "RetryingRequestsSession",
        "SyncPolicyLike",
        "SyncSessionLike",
        "default_operation",
        "default_result_classifier",
        "is_idempotent_method",
        "request_with_retry",
    ]
