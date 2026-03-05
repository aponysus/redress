# tests/test_grpc_contrib.py

import asyncio
from typing import Any

import pytest

from redress import AsyncRetryPolicy, ErrorClass, RetryPolicy
from redress.contrib.grpc import (
    aio_unary_unary_client_interceptor,
    default_operation,
    rpc_method_name,
    rpc_service_name,
    unary_unary_client_interceptor,
)


class _CallDetails:
    def __init__(self, method: object) -> None:
        self.method = method


class _SyncCall:
    def __init__(
        self,
        *,
        value: object | None = None,
        error: BaseException | None = None,
        done: bool = True,
    ) -> None:
        self.value = value
        self.error = error
        self._done = done

    def done(self) -> bool:
        return self._done

    def result(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value


class _AsyncCall:
    def __init__(self, *, value: object | None = None, error: BaseException | None = None) -> None:
        self.value = value
        self.error = error

    def __await__(self):
        async def _run():
            if self.error is not None:
                raise self.error
            return self.value

        return _run().__await__()


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


class _RetryableError(Exception):
    pass


def test_default_operation_from_method_path() -> None:
    details = _CallDetails("/pkg.Echo/Unary")
    assert default_operation(details) == "grpc /pkg.Echo/Unary"


def test_default_operation_from_bytes_method() -> None:
    details = _CallDetails(b"/pkg.Echo/Unary")
    assert default_operation(details) == "grpc /pkg.Echo/Unary"


def test_rpc_service_and_method_name() -> None:
    details = _CallDetails("/pkg.Echo/Unary")
    assert rpc_service_name(details) == "pkg.Echo"
    assert rpc_method_name(details) == "Unary"


def test_rpc_name_helpers_invalid_path() -> None:
    details = _CallDetails("invalid")
    assert rpc_service_name(details) is None
    assert rpc_method_name(details) is None


def test_unary_unary_interceptor_calls_policy_with_default_operation() -> None:
    pytest.importorskip("grpc")
    policy = _FakeSyncPolicy()
    interceptor = unary_unary_client_interceptor(policy)
    details = _CallDetails("/pkg.Echo/Unary")

    def continuation(_details: _CallDetails, _request: object) -> _SyncCall:
        return _SyncCall(value="ok")

    call = interceptor.intercept_unary_unary(continuation, details, object())
    assert call.result() == "ok"
    assert policy.calls == [{"operation": "grpc /pkg.Echo/Unary"}]


def test_unary_unary_interceptor_skip_if_bypasses_policy() -> None:
    pytest.importorskip("grpc")
    policy = _FakeSyncPolicy()
    interceptor = unary_unary_client_interceptor(
        policy,
        skip_if=lambda details, _request: details.method == "/pkg.Echo/Unary",
    )
    details = _CallDetails("/pkg.Echo/Unary")

    def continuation(_details: _CallDetails, _request: object) -> _SyncCall:
        return _SyncCall(value="ok")

    call = interceptor.intercept_unary_unary(continuation, details, object())
    assert call.result() == "ok"
    assert policy.calls == []


def test_unary_unary_interceptor_call_kwargs_provider() -> None:
    pytest.importorskip("grpc")
    policy = _FakeSyncPolicy()
    interceptor = unary_unary_client_interceptor(
        policy,
        call_kwargs=lambda details, _request: {
            "operation": f"op:{details.method}",
            "tags": {"x": 1},
        },
    )
    details = _CallDetails("/pkg.Echo/Unary")

    def continuation(_details: _CallDetails, _request: object) -> _SyncCall:
        return _SyncCall(value="ok")

    call = interceptor.intercept_unary_unary(continuation, details, object())
    assert call.result() == "ok"
    assert policy.calls == [{"operation": "op:/pkg.Echo/Unary", "tags": {"x": 1}}]


def test_unary_unary_interceptor_retries_done_call_errors() -> None:
    pytest.importorskip("grpc")
    attempts = {"count": 0}

    def continuation(_details: _CallDetails, _request: object) -> _SyncCall:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _SyncCall(error=_RetryableError("boom"), done=True)
        return _SyncCall(value="ok", done=True)

    policy = RetryPolicy(
        classifier=lambda _exc: ErrorClass.TRANSIENT,
        strategy=lambda _ctx: 0.0,
        max_attempts=4,
        deadline_s=1.0,
    )
    interceptor = unary_unary_client_interceptor(policy)
    details = _CallDetails("/pkg.Echo/Unary")
    call = interceptor.intercept_unary_unary(continuation, details, object())
    assert call.result() == "ok"
    assert attempts["count"] == 3


def test_unary_unary_interceptor_does_not_block_pending_calls() -> None:
    pytest.importorskip("grpc")
    attempts = {"count": 0}

    def continuation(_details: _CallDetails, _request: object) -> _SyncCall:
        attempts["count"] += 1
        return _SyncCall(value="ok", done=False)

    policy = RetryPolicy(
        classifier=lambda _exc: ErrorClass.TRANSIENT,
        strategy=lambda _ctx: 0.0,
        max_attempts=4,
        deadline_s=1.0,
    )
    interceptor = unary_unary_client_interceptor(policy)
    details = _CallDetails("/pkg.Echo/Unary")
    call = interceptor.intercept_unary_unary(continuation, details, object())
    assert call.result() == "ok"
    assert attempts["count"] == 1


def test_aio_interceptor_calls_policy_with_default_operation() -> None:
    pytest.importorskip("grpc")
    policy = _FakeAsyncPolicy()
    interceptor = aio_unary_unary_client_interceptor(policy)
    details = _CallDetails("/pkg.Echo/Unary")

    async def continuation(_details: _CallDetails, _request: object) -> _AsyncCall:
        return _AsyncCall(value="ok")

    async def run() -> Any:
        call = await interceptor.intercept_unary_unary(continuation, details, object())
        return await call

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == [{"operation": "grpc /pkg.Echo/Unary"}]


def test_aio_interceptor_skip_if_bypasses_policy() -> None:
    pytest.importorskip("grpc")
    policy = _FakeAsyncPolicy()
    interceptor = aio_unary_unary_client_interceptor(
        policy,
        skip_if=lambda details, _request: details.method == "/pkg.Echo/Unary",
    )
    details = _CallDetails("/pkg.Echo/Unary")

    async def continuation(_details: _CallDetails, _request: object) -> _AsyncCall:
        return _AsyncCall(value="ok")

    async def run() -> Any:
        call = await interceptor.intercept_unary_unary(continuation, details, object())
        return await call

    result = asyncio.run(run())
    assert result == "ok"
    assert policy.calls == []


def test_aio_interceptor_retries_errors() -> None:
    pytest.importorskip("grpc")
    attempts = {"count": 0}

    async def continuation(_details: _CallDetails, _request: object) -> _AsyncCall:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _AsyncCall(error=_RetryableError("boom"))
        return _AsyncCall(value="ok")

    policy = AsyncRetryPolicy(
        classifier=lambda _exc: ErrorClass.TRANSIENT,
        strategy=lambda _ctx: 0.0,
        max_attempts=4,
        deadline_s=1.0,
    )
    interceptor = aio_unary_unary_client_interceptor(policy)
    details = _CallDetails("/pkg.Echo/Unary")

    async def run() -> Any:
        call = await interceptor.intercept_unary_unary(continuation, details, object())
        return await call

    result = asyncio.run(run())
    assert result == "ok"
    assert attempts["count"] == 3
