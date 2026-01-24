"""Optional helper classifiers for common domains (HTTP status, SQLSTATE).
Dependency-free: these functions inspect attributes/args without importing client libs.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import cast

from .classify import Classification, default_classifier
from .errors import ErrorClass

_SQLSTATE_RE = re.compile(r"\b([0-9A-Z]{5})\b")


def _coerce_status(exc: BaseException) -> int | None:
    for attr in ("status", "status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    # Common pattern in HTTP libraries: args may include status
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, int) and 100 <= arg <= 599:
            return arg
    return None


def http_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify errors that expose an HTTP status/status_code/code attribute or arg.
    """
    status = _coerce_status(exc)
    if status is None:
        return default_classifier(exc)

    if status in {401, 403}:
        return ErrorClass.AUTH if status == 401 else ErrorClass.PERMISSION
    if status == 409:
        return ErrorClass.CONCURRENCY
    if status == 429:
        return ErrorClass.RATE_LIMIT
    if status == 408:
        return ErrorClass.TRANSIENT
    if 500 <= status < 600:
        return ErrorClass.SERVER_ERROR
    if status in {400, 404}:
        return ErrorClass.PERMANENT
    return ErrorClass.UNKNOWN


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


def _parse_retry_after(value: str) -> float | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        delta = (parsed - datetime.now(UTC)).total_seconds()
        return max(0.0, delta)
    return max(0.0, float(seconds))


def _coerce_retry_after(exc: BaseException) -> float | None:
    direct = getattr(exc, "retry_after", None)
    if isinstance(direct, int | float):
        return max(0.0, float(direct))
    if isinstance(direct, str):
        parsed = _parse_retry_after(direct)
        if parsed is not None:
            return parsed

    response = getattr(exc, "response", None)
    headers = getattr(exc, "headers", None) or getattr(response, "headers", None)
    header_val = _lookup_header(headers, "Retry-After")
    if header_val is None:
        return None
    return _parse_retry_after(header_val)


def http_retry_after_classifier(exc: BaseException) -> ErrorClass | Classification:
    """
    HTTP classifier that returns Classification with retry_after_s when available.
    """
    klass = http_classifier(exc)
    if klass is not ErrorClass.RATE_LIMIT:
        return klass

    retry_after_s = _coerce_retry_after(exc)
    if retry_after_s is None:
        return klass
    return Classification(klass=klass, retry_after_s=retry_after_s)


def _extract_sqlstate(args: Iterable[object]) -> str | None:
    for arg in args:
        if isinstance(arg, str):
            match = _SQLSTATE_RE.search(arg)
            if match:
                return match.group(1)
    return None


def sqlstate_classifier(exc: BaseException) -> ErrorClass:
    """
    Map SQLSTATE codes (pyodbc/DBAPI-style) into ErrorClass.
    """
    sqlstate = getattr(exc, "sqlstate", None) or _extract_sqlstate(getattr(exc, "args", ()))
    if sqlstate is None:
        return default_classifier(exc)

    code = str(sqlstate)
    if code in {"40001", "40P01"}:
        return ErrorClass.CONCURRENCY
    if code in {"HYT00", "HYT01", "08S01"} or code.startswith("08"):
        return ErrorClass.TRANSIENT
    if code.startswith("28"):
        return ErrorClass.AUTH
    if code in {"42000", "42P01"}:
        return ErrorClass.PERMANENT
    return ErrorClass.UNKNOWN
