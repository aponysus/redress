from __future__ import annotations

from typing import Any

import pytest

import redress.contrib.openai as openai_extra
import redress.strategies as strategies
from redress.classify import Classification
from redress.errors import ErrorClass
from redress.strategies import BackoffContext


class _Response:
    def __init__(self, status_code: int, headers: object | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class _OpenAIError(Exception):
    pass


class _APIStatusError(_OpenAIError):
    def __init__(
        self,
        status_code: int,
        *,
        headers: object | None = None,
        body: object | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(status_code)
        self.status_code = status_code
        self.response = _Response(status_code, headers)
        self.body = body or {}
        if code is not None:
            self.code = code


class _AuthenticationError(_APIStatusError):
    pass


class _PermissionDeniedError(_APIStatusError):
    pass


class _NotFoundError(_APIStatusError):
    pass


class _BadRequestError(_APIStatusError):
    pass


class _UnprocessableEntityError(_APIStatusError):
    pass


class _ConflictError(_APIStatusError):
    pass


class _RateLimitError(_APIStatusError):
    pass


class _InternalServerError(_APIStatusError):
    pass


class _APITimeoutError(_OpenAIError):
    pass


class _APIConnectionError(_OpenAIError):
    pass


class _APIResponseValidationError(_OpenAIError):
    pass


class _OpenAIModule:
    OpenAIError = _OpenAIError
    APIStatusError = _APIStatusError
    AuthenticationError = _AuthenticationError
    PermissionDeniedError = _PermissionDeniedError
    NotFoundError = _NotFoundError
    BadRequestError = _BadRequestError
    UnprocessableEntityError = _UnprocessableEntityError
    ConflictError = _ConflictError
    RateLimitError = _RateLimitError
    InternalServerError = _InternalServerError
    APITimeoutError = _APITimeoutError
    APIConnectionError = _APIConnectionError
    APIResponseValidationError = _APIResponseValidationError


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_import(name: str) -> Any:
        if name == "openai":
            return _OpenAIModule
        raise AssertionError(name)

    monkeypatch.setattr(openai_extra.importlib, "import_module", fake_import)


def test_openai_classifier_raises_clean_import_error_when_openai_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(openai_extra.importlib, "import_module", fake_import)

    with pytest.raises(ImportError, match=r"pip install redress\[openai\]"):
        openai_extra.openai_classifier(RuntimeError("boom"))


def test_openai_classifier_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch)

    assert openai_extra.openai_classifier(_AuthenticationError(401)) is ErrorClass.AUTH
    assert openai_extra.openai_classifier(_PermissionDeniedError(403)) is ErrorClass.PERMISSION
    assert openai_extra.openai_classifier(_NotFoundError(404)) is ErrorClass.PERMANENT
    assert openai_extra.openai_classifier(_BadRequestError(400, code="context_length_exceeded")) is (
        ErrorClass.PERMANENT
    )
    assert openai_extra.openai_classifier(_UnprocessableEntityError(422)) is ErrorClass.PERMANENT
    assert openai_extra.openai_classifier(_ConflictError(409)) is ErrorClass.CONCURRENCY
    assert openai_extra.openai_classifier(_APITimeoutError("timeout")) is ErrorClass.TRANSIENT
    assert openai_extra.openai_classifier(_APIConnectionError("conn")) is ErrorClass.TRANSIENT
    assert openai_extra.openai_classifier(_APIResponseValidationError("schema")) is (
        ErrorClass.PERMANENT
    )
    assert openai_extra.openai_classifier(_OpenAIError("misc")) is ErrorClass.UNKNOWN


def test_openai_classifier_falls_back_for_non_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch)
    assert openai_extra.openai_classifier(TimeoutError("timeout")) is ErrorClass.TRANSIENT


def test_openai_classifier_rate_limit_insufficient_quota_is_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch)

    err = _RateLimitError(429, body={"code": "insufficient_quota"})
    assert openai_extra.openai_classifier(err) is ErrorClass.PERMANENT


def test_openai_classifier_prefers_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch)

    err = _RateLimitError(
        429,
        headers={"Retry-After": "2", "x-ratelimit-reset-requests": "1s"},
    )
    result = openai_extra.openai_classifier(err)
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 2.0
    assert result.details["retry_after_source"] == "Retry-After"


def test_openai_classifier_uses_smallest_reset_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch)

    err = _RateLimitError(
        429,
        headers={
            "x-ratelimit-reset-requests": "6m0s",
            "x-ratelimit-reset-tokens": "1.2s",
        },
    )
    result = openai_extra.openai_classifier(err)
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 1.2
    assert result.details["retry_after_source"] == "x-ratelimit-reset-tokens"


def test_openai_classifier_status_error_mappings(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_openai(monkeypatch)

    transient = openai_extra.openai_classifier(_APIStatusError(425, headers={"Retry-After": "3"}))
    assert isinstance(transient, Classification)
    assert transient.klass is ErrorClass.TRANSIENT
    assert transient.retry_after_s == 3.0

    server = openai_extra.openai_classifier(_InternalServerError(503, headers={"Retry-After": "4"}))
    assert isinstance(server, Classification)
    assert server.klass is ErrorClass.SERVER_ERROR
    assert server.retry_after_s == 4.0

    assert openai_extra.openai_classifier(_APIStatusError(418)) is ErrorClass.UNKNOWN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1s", 1.0),
        ("1.2s", 1.2),
        ("6m0s", 360.0),
        ("1h2m3s", 3723.0),
    ],
)
def test_parse_reset_duration_supported_forms(raw: str, expected: float) -> None:
    assert openai_extra._parse_reset_duration(raw) == expected


@pytest.mark.parametrize("raw", ["", "junk", "1ms", "1m2", "s"])
def test_parse_reset_duration_rejects_invalid_values(raw: str) -> None:
    assert openai_extra._parse_reset_duration(raw) is None


def test_openai_aware_backoff_uses_fallback_without_retry_hint() -> None:
    strat = openai_extra.openai_aware_backoff(
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


def test_openai_aware_backoff_clamps_retry_after_to_max_s() -> None:
    strat = openai_extra.openai_aware_backoff(
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


def test_openai_aware_backoff_does_not_reclamp_after_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_uniform = strategies.random.uniform
    monkeypatch.setattr(strategies.random, "uniform", lambda _a, _b: 0.25)
    try:
        strat = openai_extra.openai_aware_backoff(
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


def test_openai_aware_backoff_still_respects_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_uniform = strategies.random.uniform
    monkeypatch.setattr(strategies.random, "uniform", lambda _a, _b: 0.25)
    try:
        strat = openai_extra.openai_aware_backoff(
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
