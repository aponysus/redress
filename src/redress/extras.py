"""Optional helper classifiers for common domains (HTTP status, SQLSTATE).
Dependency-free: these functions inspect attributes/args without importing client libs.
"""

import re
from collections.abc import Iterable

from .classify import default_classifier
from .errors import ErrorClass

_SQLSTATE_RE = re.compile(r"\b([0-9A-Z]{5})\b")


def _coerce_status(exc: BaseException) -> int | None:
    for attr in ("status", "status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    # Common pattern in HTTP libraries: args may include status
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, int):
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
