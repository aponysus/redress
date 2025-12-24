"""
Example pyodbc-aware classifier for redress.

Maps common SQLSTATE/driver codes to ErrorClass without importing pyodbc as a dependency.
Adapt the mappings to your environment (SQL Server/Postgres) and driver behaviors.
"""

import re
from collections.abc import Iterable

from redress.errors import ErrorClass

_SQLSTATE_RE = re.compile(r"\[([0-9A-Z]{5})\]")


def _extract_sqlstate(args: Iterable[object]) -> str | None:
    """
    Try to pull a 5-character SQLSTATE (e.g., HYT00, 40001) out of pyodbc args.
    """
    for arg in args:
        if isinstance(arg, str):
            match = _SQLSTATE_RE.search(arg)
            if match:
                return match.group(1)
    return None


def pyodbc_classifier(exc: BaseException) -> ErrorClass:
    """
    Map pyodbc exceptions to coarse error classes.
    """
    sqlstate = getattr(exc, "sqlstate", None) or _extract_sqlstate(getattr(exc, "args", ()))
    code = str(sqlstate) if sqlstate is not None else None

    if code is not None:
        # Concurrency/serialization conflicts
        if code in {"40001", "40P01"}:
            return ErrorClass.CONCURRENCY

        # Timeouts and connection issues (driver/network)
        if code in {"HYT00", "HYT01", "08S01"} or code.startswith("08"):
            return ErrorClass.TRANSIENT

        # Auth/permission failures (do not retry)
        if code.startswith("28"):
            return ErrorClass.AUTH

        # Syntax or object-not-found; treat as permanent
        if code in {"42000", "42P01"}:
            return ErrorClass.PERMANENT

    # Fallback: let unknowns be retried according to policy defaults
    return ErrorClass.UNKNOWN
