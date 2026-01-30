"""Optional helper for pyodbc-style exceptions.

This module has no pyodbc dependency; it re-exports the extras implementation.
"""

from redress.extras import pyodbc_classifier

__all__ = ["pyodbc_classifier"]
