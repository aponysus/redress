from enum import Enum, auto


class ErrorClass(Enum):
    """
    Coarse-grained error categories used by RetryPolicy and strategies.

    This is intentionally small and generic so that:
      * You can map many different domain-specific exceptions into it.
      * Backoff behavior can be tuned per class.
    """

    AUTH = auto()
    PERMISSION = auto()
    PERMANENT = auto()
    CONCURRENCY = auto()
    RATE_LIMIT = auto()
    SERVER_ERROR = auto()
    TRANSIENT = auto()
    UNKNOWN = auto()


class PermanentError(Exception):
    """Explicit marker that this error should not be retried."""

    pass


class RateLimitError(Exception):
    """Explicit marker for rate-limit conditions (429, quotas, etc.)."""

    pass


class ConcurrencyError(Exception):
    """Explicit marker for 409-style concurrency conflicts."""

    pass


class ServerError(Exception):
    """Explicit marker for 5xx-style server errors."""

    pass
