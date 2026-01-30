"""Optional SQLSTATE classifier (dependency-free)."""

import re
from collections.abc import Iterable

from ..classify import default_classifier
from ..errors import ErrorClass

_SQLSTATE_RE = re.compile(r"\b([0-9A-Z]{5})\b")


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
