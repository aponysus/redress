from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class ErrorClass(Enum):
    """
    Coarse-grained error categories used by Retry/RetryPolicy and strategies.

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


class StopReason(str, Enum):
    MAX_ATTEMPTS_GLOBAL = "MAX_ATTEMPTS_GLOBAL"
    MAX_ATTEMPTS_PER_CLASS = "MAX_ATTEMPTS_PER_CLASS"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    MAX_UNKNOWN_ATTEMPTS = "MAX_UNKNOWN_ATTEMPTS"
    NON_RETRYABLE_CLASS = "NON_RETRYABLE_CLASS"
    NO_STRATEGY = "NO_STRATEGY"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class RetryExhaustedError(Exception):
    stop_reason: StopReason
    attempts: int
    last_class: ErrorClass | None
    last_exception: BaseException | None
    last_result: Any | None

    def __str__(self) -> str:
        return f"Retry stopped: {self.stop_reason.value}"


class AbortRetryError(Exception):
    """
    Raised to cooperatively abort retry execution.
    """


AbortRetry = AbortRetryError


class CircuitOpenError(Exception):
    """
    Raised when a circuit breaker rejects a call.
    """

    def __init__(self, state: str = "open") -> None:
        self.state = state
        super().__init__(f"Circuit is {state}.")


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
