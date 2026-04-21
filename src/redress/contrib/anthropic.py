"""Anthropic integration helpers."""

import importlib
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from ..classify import Classification, default_classifier
from ..errors import ErrorClass
from ..extras import _parse_retry_after
from ..strategies import BackoffContext, StrategyFn, decorrelated_jitter, retry_after_or


def _anthropic_module() -> Any:
    try:
        return importlib.import_module("anthropic")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "anthropic is required for redress.contrib.anthropic; pip install redress[anthropic]"
        ) from exc


def _lookup_header(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    if isinstance(headers, Mapping):
        try:
            value = headers.get(name)
            if value is None:
                value = headers.get(name.lower())
            if value is not None:
                return str(value)
            for key, val in headers.items():
                if str(key).lower() == name.lower():
                    return str(val)
            return None
        except Exception:
            return None
    try:
        getter = getattr(headers, "get", None)
        if callable(getter):
            value = getter(name)
            if value is None:
                value = getter(name.lower())
            if value is not None:
                return str(value)
            items = getattr(headers, "items", None)
            if callable(items):
                for key, val in items():
                    if str(key).lower() == name.lower():
                        return str(val)
                return None
    except Exception:
        return None

    try:
        for key, val in cast(Iterable[tuple[object, object]], headers):
            if str(key).lower() == name.lower():
                return str(val)
    except Exception:
        return None
    return None


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_rfc3339_reset(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = (parsed - _now_utc()).total_seconds()
    return max(0.0, delta)


def _retry_after_from_headers(headers: object) -> tuple[float | None, str | None]:
    retry_after_header = _lookup_header(headers, "Retry-After")
    retry_after = _parse_retry_after(retry_after_header) if retry_after_header is not None else None
    if retry_after is not None:
        return retry_after, "Retry-After"

    resets: list[tuple[float, str]] = []
    for header in (
        "anthropic-ratelimit-requests-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-input-tokens-reset",
        "anthropic-ratelimit-output-tokens-reset",
    ):
        parsed = _parse_rfc3339_reset(_lookup_header(headers, header))
        if parsed is not None:
            resets.append((parsed, header))

    if not resets:
        return None, None
    delay_s, source = min(resets, key=lambda item: item[0])
    return delay_s, source


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    if isinstance(value, int):
        return value
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _error_type(exc: BaseException) -> str | None:
    error_type = getattr(exc, "type", None)
    if isinstance(error_type, str):
        return error_type

    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            nested_type = error.get("type")
            if isinstance(nested_type, str):
                return nested_type
    return None


def _retry_after_from_exc(exc: BaseException) -> tuple[float | None, str | None]:
    response = getattr(exc, "response", None)
    headers = getattr(exc, "headers", None) or getattr(response, "headers", None)
    return _retry_after_from_headers(headers)


def _is_provider_error(exc: BaseException, provider: object, name: str) -> bool:
    error_type = getattr(provider, name, None)
    return (
        isinstance(error_type, type)
        and issubclass(error_type, BaseException)
        and isinstance(exc, error_type)
    )


def _classification_with_retry_after(
    klass: ErrorClass,
    retry_after_s: float | None,
    *,
    source: str | None = None,
) -> ErrorClass | Classification:
    if retry_after_s is None:
        return klass
    details = {"retry_after_source": source} if source is not None else {}
    return Classification(klass=klass, retry_after_s=retry_after_s, details=details)


def anthropic_classifier(exc: BaseException) -> ErrorClass | Classification:
    """
    Classify Anthropic SDK exceptions into redress ErrorClass values.
    """
    anthropic = _anthropic_module()

    if _is_provider_error(exc, anthropic, "AuthenticationError"):
        return ErrorClass.AUTH
    if _is_provider_error(exc, anthropic, "PermissionDeniedError"):
        return ErrorClass.PERMISSION
    if _is_provider_error(exc, anthropic, "NotFoundError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, anthropic, "BadRequestError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, anthropic, "RequestTooLargeError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, anthropic, "UnprocessableEntityError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, anthropic, "ConflictError"):
        return ErrorClass.CONCURRENCY
    if _is_provider_error(exc, anthropic, "RateLimitError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.RATE_LIMIT,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, anthropic, "OverloadedError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.SERVER_ERROR,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, anthropic, "ServiceUnavailableError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.SERVER_ERROR,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, anthropic, "DeadlineExceededError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.SERVER_ERROR,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, anthropic, "InternalServerError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.SERVER_ERROR,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, anthropic, "APITimeoutError"):
        return ErrorClass.TRANSIENT
    if _is_provider_error(exc, anthropic, "APIConnectionError"):
        return ErrorClass.TRANSIENT
    if _is_provider_error(exc, anthropic, "APIResponseValidationError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, anthropic, "APIStatusError"):
        status = _status_code(exc)
        if status == 413:
            return ErrorClass.PERMANENT
        if _error_type(exc) == "overloaded_error":
            retry_after_s, source = _retry_after_from_exc(exc)
            return _classification_with_retry_after(
                ErrorClass.SERVER_ERROR,
                retry_after_s,
                source=source,
            )
        if status in {408, 425}:
            retry_after_s, source = _retry_after_from_exc(exc)
            return _classification_with_retry_after(
                ErrorClass.TRANSIENT,
                retry_after_s,
                source=source,
            )
        if status in {500, 503, 504, 529}:
            retry_after_s, source = _retry_after_from_exc(exc)
            return _classification_with_retry_after(
                ErrorClass.SERVER_ERROR,
                retry_after_s,
                source=source,
            )
        return ErrorClass.UNKNOWN
    if _is_provider_error(exc, anthropic, "AnthropicError"):
        return ErrorClass.UNKNOWN
    return default_classifier(exc)


def _clamp_retry_after(max_s: float, strategy: Callable[[BackoffContext], float]) -> StrategyFn:
    def f(ctx: BackoffContext) -> float:
        retry_after = ctx.classification.retry_after_s
        if retry_after is None or not math.isfinite(retry_after):
            return strategy(ctx)

        clamped = min(max_s, max(0.0, float(retry_after)))
        if clamped == retry_after:
            return strategy(ctx)

        updated = replace(
            ctx,
            classification=replace(ctx.classification, retry_after_s=clamped),
        )
        return strategy(updated)

    return f


def anthropic_aware_backoff(
    *,
    base_s: float = 0.5,
    max_s: float = 30.0,
    jitter_s: float = 0.25,
    fallback: StrategyFn | None = None,
) -> StrategyFn:
    """
    Return a retry strategy that honors Anthropic retry hints with LLM-tuned defaults.
    """
    fallback_strategy = fallback or decorrelated_jitter(base_s=base_s, max_s=max_s)
    base_strategy = cast(
        Callable[[BackoffContext], float],
        retry_after_or(fallback_strategy, jitter_s=jitter_s),
    )
    return _clamp_retry_after(max_s, base_strategy)


__all__ = [
    "anthropic_aware_backoff",
    "anthropic_classifier",
]
