from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, ParamSpec, TypeVar

from ..classify import Classification
from ..errors import ErrorClass, StopReason

FailureCause = Literal["exception", "result"]
ClassifierFn = Callable[[BaseException], ErrorClass | Classification]
MetricHook = Callable[[str, int, float, dict[str, Any]], None]
LogHook = Callable[[str, dict[str, Any]], None]
AbortPredicate = Callable[[], bool]
P = ParamSpec("P")
T = TypeVar("T")


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
