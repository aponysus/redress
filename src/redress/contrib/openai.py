"""OpenAI integration helpers."""

import importlib
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any, cast

from ..classify import Classification, default_classifier
from ..errors import ErrorClass
from ..extras import _parse_retry_after
from ..strategies import BackoffContext, StrategyFn, decorrelated_jitter, retry_after_or

_RESET_DURATION_RE = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
)


def _openai_module() -> Any:
    try:
        return importlib.import_module("openai")
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "openai is required for redress.contrib.openai; pip install redress[openai]"
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


def _parse_reset_duration(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    match = _RESET_DURATION_RE.fullmatch(raw)
    if match is None:
        return None
    if not any(match.group(name) is not None for name in ("hours", "minutes", "seconds")):
        return None

    hours = int(match.group("hours") or "0")
    minutes = int(match.group("minutes") or "0")
    seconds = float(match.group("seconds") or "0")
    return max(0.0, hours * 3600.0 + minutes * 60.0 + seconds)


def _retry_after_from_headers(headers: object) -> tuple[float | None, str | None]:
    retry_after_header = _lookup_header(headers, "Retry-After")
    retry_after = _parse_retry_after(retry_after_header) if retry_after_header is not None else None
    if retry_after is not None:
        return retry_after, "Retry-After"

    resets: list[tuple[float, str]] = []
    for header in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        parsed = _parse_reset_duration(_lookup_header(headers, header))
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


def _error_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code

    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        body_code = body.get("code")
        if isinstance(body_code, str):
            return body_code
        nested = body.get("error")
        if isinstance(nested, Mapping):
            nested_code = nested.get("code")
            if isinstance(nested_code, str):
                return nested_code
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


def openai_classifier(exc: BaseException) -> ErrorClass | Classification:
    """
    Classify OpenAI SDK exceptions into redress ErrorClass values.
    """
    openai = _openai_module()

    if _is_provider_error(exc, openai, "AuthenticationError"):
        return ErrorClass.AUTH
    if _is_provider_error(exc, openai, "PermissionDeniedError"):
        return ErrorClass.PERMISSION
    if _is_provider_error(exc, openai, "NotFoundError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, openai, "BadRequestError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, openai, "UnprocessableEntityError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, openai, "ConflictError"):
        return ErrorClass.CONCURRENCY
    if _is_provider_error(exc, openai, "RateLimitError"):
        if _error_code(exc) == "insufficient_quota":
            return ErrorClass.PERMANENT
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.RATE_LIMIT,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, openai, "InternalServerError"):
        retry_after_s, source = _retry_after_from_exc(exc)
        return _classification_with_retry_after(
            ErrorClass.SERVER_ERROR,
            retry_after_s,
            source=source,
        )
    if _is_provider_error(exc, openai, "APITimeoutError"):
        return ErrorClass.TRANSIENT
    if _is_provider_error(exc, openai, "APIConnectionError"):
        return ErrorClass.TRANSIENT
    if _is_provider_error(exc, openai, "APIResponseValidationError"):
        return ErrorClass.PERMANENT
    if _is_provider_error(exc, openai, "APIStatusError"):
        status = _status_code(exc)
        if status in {408, 425}:
            retry_after_s, source = _retry_after_from_exc(exc)
            return _classification_with_retry_after(
                ErrorClass.TRANSIENT,
                retry_after_s,
                source=source,
            )
        if status in {500, 502, 503, 504}:
            retry_after_s, source = _retry_after_from_exc(exc)
            return _classification_with_retry_after(
                ErrorClass.SERVER_ERROR,
                retry_after_s,
                source=source,
            )
        return ErrorClass.UNKNOWN
    if _is_provider_error(exc, openai, "OpenAIError"):
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


def openai_aware_backoff(
    *,
    base_s: float = 0.5,
    max_s: float = 30.0,
    jitter_s: float = 0.25,
    fallback: StrategyFn | None = None,
) -> StrategyFn:
    """
    Return a retry strategy that honors OpenAI retry hints with LLM-tuned defaults.
    """
    fallback_strategy = fallback or decorrelated_jitter(base_s=base_s, max_s=max_s)
    base_strategy = cast(
        Callable[[BackoffContext], float],
        retry_after_or(fallback_strategy, jitter_s=jitter_s),
    )
    return _clamp_retry_after(max_s, base_strategy)


__all__ = [
    "openai_aware_backoff",
    "openai_classifier",
]
