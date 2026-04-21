from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import redress.contrib.anthropic as anthropic_extra
import redress.strategies as strategies
from redress.classify import Classification
from redress.errors import ErrorClass
from redress.strategies import BackoffContext


class _Request:
    pass


class _Response:
    def __init__(self, status_code: int, headers: object | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.request = _Request()


class _AnthropicError(Exception):
    pass


class _APIError(_AnthropicError):
    def __init__(self, message: str, request: object, *, body: object | None) -> None:
        super().__init__(message)
        self.message = message
        self.request = request
        self.body = body


class _APIResponseValidationError(_APIError):
    def __init__(self, response: _Response, body: object | None) -> None:
        super().__init__("invalid schema", response.request, body=body)
        self.response = response
        self.status_code = response.status_code


class _APIStatusError(_APIError):
    def __init__(
        self, status_code: int, *, headers: object | None = None, body: object | None = None
    ) -> None:
        response = _Response(status_code, headers)
        super().__init__("status error", response.request, body=body)
        self.response = response
        self.status_code = response.status_code
        self.request_id = response.headers.get("request-id")
        self.type = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                nested_type = error.get("type")
                if isinstance(nested_type, str):
                    self.type = nested_type


class _BadRequestError(_APIStatusError):
    pass


class _AuthenticationError(_APIStatusError):
    pass


class _PermissionDeniedError(_APIStatusError):
    pass


class _NotFoundError(_APIStatusError):
    pass


class _ConflictError(_APIStatusError):
    pass


class _RequestTooLargeError(_APIStatusError):
    pass


class _UnprocessableEntityError(_APIStatusError):
    pass


class _RateLimitError(_APIStatusError):
    pass


class _ServiceUnavailableError(_APIStatusError):
    pass


class _OverloadedError(_APIStatusError):
    pass


class _DeadlineExceededError(_APIStatusError):
    pass


class _InternalServerError(_APIStatusError):
    pass


class _APIConnectionError(_APIError):
    def __init__(self) -> None:
        super().__init__("conn", _Request(), body=None)


class _APITimeoutError(_APIConnectionError):
    pass


class _AnthropicModule:
    AnthropicError = _AnthropicError
    APIError = _APIError
    APIResponseValidationError = _APIResponseValidationError
    APIStatusError = _APIStatusError
    BadRequestError = _BadRequestError
    AuthenticationError = _AuthenticationError
    PermissionDeniedError = _PermissionDeniedError
    NotFoundError = _NotFoundError
    ConflictError = _ConflictError
    RequestTooLargeError = _RequestTooLargeError
    UnprocessableEntityError = _UnprocessableEntityError
    RateLimitError = _RateLimitError
    ServiceUnavailableError = _ServiceUnavailableError
    OverloadedError = _OverloadedError
    DeadlineExceededError = _DeadlineExceededError
    InternalServerError = _InternalServerError
    APIConnectionError = _APIConnectionError
    APITimeoutError = _APITimeoutError


def _install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str) -> Any:
        if name == "anthropic":
            return _AnthropicModule
        raise AssertionError(name)

    monkeypatch.setattr(anthropic_extra.importlib, "import_module", fake_import)


def test_anthropic_classifier_raises_clean_import_error_when_anthropic_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(anthropic_extra.importlib, "import_module", fake_import)

    with pytest.raises(ImportError, match=r"pip install redress\[anthropic\]"):
        anthropic_extra.anthropic_classifier(RuntimeError("boom"))


def test_anthropic_classifier_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_anthropic(monkeypatch)

    assert anthropic_extra.anthropic_classifier(_AuthenticationError(401)) is ErrorClass.AUTH
    assert (
        anthropic_extra.anthropic_classifier(_PermissionDeniedError(403)) is ErrorClass.PERMISSION
    )
    assert anthropic_extra.anthropic_classifier(_NotFoundError(404)) is ErrorClass.PERMANENT
    assert anthropic_extra.anthropic_classifier(_BadRequestError(400)) is ErrorClass.PERMANENT
    assert anthropic_extra.anthropic_classifier(_RequestTooLargeError(413)) is ErrorClass.PERMANENT
    assert anthropic_extra.anthropic_classifier(_UnprocessableEntityError(422)) is (
        ErrorClass.PERMANENT
    )
    assert anthropic_extra.anthropic_classifier(_ConflictError(409)) is ErrorClass.CONCURRENCY
    assert anthropic_extra.anthropic_classifier(_APITimeoutError()) is ErrorClass.TRANSIENT
    assert anthropic_extra.anthropic_classifier(_APIConnectionError()) is ErrorClass.TRANSIENT
    assert anthropic_extra.anthropic_classifier(
        _APIResponseValidationError(_Response(500), {})
    ) is (ErrorClass.PERMANENT)
    assert anthropic_extra.anthropic_classifier(_AnthropicError("misc")) is ErrorClass.UNKNOWN


def test_anthropic_classifier_falls_back_for_non_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch)
    assert anthropic_extra.anthropic_classifier(TimeoutError("timeout")) is ErrorClass.TRANSIENT


def test_anthropic_classifier_prefers_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch)

    err = _RateLimitError(
        429,
        headers={
            "Retry-After": "2",
            "anthropic-ratelimit-requests-reset": "2026-01-01T00:00:01Z",
        },
    )
    result = anthropic_extra.anthropic_classifier(err)
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 2.0
    assert result.details["retry_after_source"] == "Retry-After"


def test_anthropic_classifier_uses_smallest_reset_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(anthropic_extra, "_now_utc", lambda: now)

    err = _RateLimitError(
        429,
        headers={
            "anthropic-ratelimit-requests-reset": (now + timedelta(seconds=6)).isoformat(),
            "anthropic-ratelimit-input-tokens-reset": (now + timedelta(seconds=2)).isoformat(),
        },
    )
    result = anthropic_extra.anthropic_classifier(err)
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 2.0
    assert result.details["retry_after_source"] == "anthropic-ratelimit-input-tokens-reset"


def test_anthropic_classifier_overloaded_and_status_error_mappings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch)

    overloaded = anthropic_extra.anthropic_classifier(
        _APIStatusError(503, body={"error": {"type": "overloaded_error"}})
    )
    assert overloaded is ErrorClass.SERVER_ERROR

    assert anthropic_extra.anthropic_classifier(_OverloadedError(529)) is ErrorClass.SERVER_ERROR
    assert anthropic_extra.anthropic_classifier(_ServiceUnavailableError(503)) is (
        ErrorClass.SERVER_ERROR
    )
    assert anthropic_extra.anthropic_classifier(_DeadlineExceededError(504)) is (
        ErrorClass.SERVER_ERROR
    )
    assert anthropic_extra.anthropic_classifier(_APIStatusError(413)) is ErrorClass.PERMANENT
    assert anthropic_extra.anthropic_classifier(_APIStatusError(425)) is ErrorClass.TRANSIENT
    assert anthropic_extra.anthropic_classifier(_APIStatusError(418)) is ErrorClass.UNKNOWN


def test_anthropic_classifier_handles_malformed_body_and_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_anthropic(monkeypatch)

    err = _RateLimitError(
        429,
        headers={"anthropic-ratelimit-requests-reset": "junk"},
        body="not-a-dict",
    )
    assert anthropic_extra.anthropic_classifier(err) is ErrorClass.RATE_LIMIT

    status_err = _APIStatusError(503, headers={"Retry-After": "junk"}, body={"error": "oops"})
    assert anthropic_extra.anthropic_classifier(status_err) is ErrorClass.SERVER_ERROR


def test_parse_rfc3339_reset() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    future = now + timedelta(seconds=5)
    original_now = anthropic_extra._now_utc
    try:
        anthropic_extra._now_utc = lambda: now
        assert anthropic_extra._parse_rfc3339_reset(future.isoformat()) == 5.0
        assert anthropic_extra._parse_rfc3339_reset("2026-01-01T00:00:05Z") == 5.0
        assert anthropic_extra._parse_rfc3339_reset("junk") is None
    finally:
        anthropic_extra._now_utc = original_now


def test_anthropic_aware_backoff_uses_fallback_without_retry_hint() -> None:
    strat = anthropic_extra.anthropic_aware_backoff(
        jitter_s=0.0,
        fallback=lambda _ctx: 1.5,
    )
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=10.0,
        cause="exception",
    )
    assert strat(ctx) == 1.5


def test_anthropic_aware_backoff_clamps_retry_after_to_max_s() -> None:
    strat = anthropic_extra.anthropic_aware_backoff(
        max_s=30.0,
        jitter_s=0.0,
        fallback=lambda _ctx: 1.0,
    )
    ctx = BackoffContext(
        attempt=1,
        classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=60.0),
        prev_sleep_s=None,
        remaining_s=100.0,
        cause="exception",
    )
    assert strat(ctx) == 30.0


def test_anthropic_aware_backoff_does_not_reclamp_after_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_uniform = strategies.random.uniform
    monkeypatch.setattr(strategies.random, "uniform", lambda _a, _b: 0.25)
    try:
        strat = anthropic_extra.anthropic_aware_backoff(
            max_s=30.0,
            jitter_s=0.25,
            fallback=lambda _ctx: 1.0,
        )
        ctx = BackoffContext(
            attempt=1,
            classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=60.0),
            prev_sleep_s=None,
            remaining_s=100.0,
            cause="exception",
        )
        assert strat(ctx) == 30.25
    finally:
        monkeypatch.setattr(strategies.random, "uniform", original_uniform)


def test_anthropic_aware_backoff_still_respects_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_uniform = strategies.random.uniform
    monkeypatch.setattr(strategies.random, "uniform", lambda _a, _b: 0.25)
    try:
        strat = anthropic_extra.anthropic_aware_backoff(
            max_s=30.0,
            jitter_s=0.25,
            fallback=lambda _ctx: 1.0,
        )
        ctx = BackoffContext(
            attempt=1,
            classification=Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=60.0),
            prev_sleep_s=None,
            remaining_s=10.0,
            cause="exception",
        )
        assert strat(ctx) == 10.0
    finally:
        monkeypatch.setattr(strategies.random, "uniform", original_uniform)


def test_anthropic_conformance_known_exception_hierarchy() -> None:
    anthropic = pytest.importorskip("anthropic")

    def walk(root: type[BaseException]) -> set[str]:
        names: set[str] = set()
        stack = [root]
        seen: set[type[BaseException]] = set()
        while stack:
            current = stack.pop()
            for child in current.__subclasses__():
                if child in seen:
                    continue
                seen.add(child)
                names.add(child.__name__)
                stack.append(child)
        return names

    expected = {
        "APIConnectionError",
        "APIError",
        "APIResponseValidationError",
        "APIStatusError",
        "APITimeoutError",
        "AuthenticationError",
        "BadRequestError",
        "ConflictError",
        "DeadlineExceededError",
        "InternalServerError",
        "MissingDependencyError",
        "MutuallyExclusiveAuthError",
        "NotFoundError",
        "OverloadedError",
        "PermissionDeniedError",
        "RateLimitError",
        "RequestTooLargeError",
        "ServiceUnavailableError",
        "StreamAlreadyConsumed",
        "UnprocessableEntityError",
    }

    discovered = walk(anthropic.AnthropicError)
    assert (
        discovered <= expected
    ), f"Unhandled Anthropic exception subclasses: {sorted(discovered - expected)}"
