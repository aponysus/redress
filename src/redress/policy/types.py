from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Literal, ParamSpec, TypeVar

from ..classify import Classification
from ..errors import ErrorClass, StopReason

FailureCause = Literal["exception", "result"]
ClassifierFn = Callable[[BaseException], ErrorClass | Classification]
MetricHook = Callable[[str, int, float, dict[str, Any]], None]
LogHook = Callable[[str, dict[str, Any]], None]
AbortPredicate = Callable[[], bool]
AttemptHook = Callable[["AttemptContext"], None]
P = ParamSpec("P")
T = TypeVar("T")


class AttemptDecision(Enum):
    SUCCESS = "success"
    RETRY = "retry"
    RAISE = "raise"
    SCHEDULED = "scheduled"
    ABORTED = "aborted"


@dataclass(frozen=True)
class AttemptContext:
    attempt: int
    operation: str | None
    elapsed_s: float
    classification: Classification | None
    exception: BaseException | None
    result: Any | None
    decision: AttemptDecision | None
    stop_reason: StopReason | None
    cause: FailureCause | None
    sleep_s: float | None


@dataclass(frozen=True)
class TimelineEvent:
    attempt: int
    event: str
    elapsed_s: float
    sleep_s: float
    error_class: ErrorClass | None
    stop_reason: StopReason | None
    cause: FailureCause | None


@dataclass
class RetryTimeline:
    events: list[TimelineEvent] = field(default_factory=list)

    def add(self, event: TimelineEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class RetryOutcome(Generic[T]):
    ok: bool
    value: T | None
    stop_reason: StopReason | None
    attempts: int
    last_class: ErrorClass | None
    last_exception: BaseException | None
    last_result: Any | None
    cause: FailureCause | None
    elapsed_s: float
    next_sleep_s: float | None = None
    timeline: RetryTimeline | None = None
