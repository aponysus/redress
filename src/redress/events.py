from enum import Enum

from .errors import StopReason


class EventName(str, Enum):
    SUCCESS = "success"
    RETRY = "retry"
    PERMANENT_FAIL = "permanent_fail"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"
    MAX_UNKNOWN_ATTEMPTS_EXCEEDED = "max_unknown_attempts_exceeded"
    NO_STRATEGY_CONFIGURED = "no_strategy_configured"
    ABORTED = "aborted"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_HALF_OPEN = "circuit_half_open"
    CIRCUIT_CLOSED = "circuit_closed"
    CIRCUIT_REJECTED = "circuit_rejected"


__all__ = ["EventName", "StopReason"]
