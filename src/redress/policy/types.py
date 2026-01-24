from collections.abc import Callable
from typing import Any, Literal, ParamSpec, TypeVar

from ..classify import Classification
from ..errors import ErrorClass

FailureCause = Literal["exception", "result"]
ClassifierFn = Callable[[BaseException], ErrorClass | Classification]
MetricHook = Callable[[str, int, float, dict[str, Any]], None]
LogHook = Callable[[str, dict[str, Any]], None]
AbortPredicate = Callable[[], bool]
P = ParamSpec("P")
T = TypeVar("T")
