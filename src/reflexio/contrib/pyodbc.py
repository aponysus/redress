"""
Optional helper for pyodbc-style exceptions.

This module has no pyodbc dependency; it reuses the SQLSTATE classifier from reflexio.extras.
"""

from __future__ import annotations

from reflexio.errors import ErrorClass
from reflexio.extras import sqlstate_classifier


def pyodbc_classifier(exc: BaseException) -> ErrorClass:
    """
    Map a pyodbc (or pyodbc-like) exception to an ErrorClass via SQLSTATE.
    """
    return sqlstate_classifier(exc)
