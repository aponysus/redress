from collections.abc import Callable
from enum import Enum

from .strategies import BackoffContext


class SleepDecision(str, Enum):
    SLEEP = "sleep"
    DEFER = "defer"
    ABORT = "abort"


SleepFn = Callable[[BackoffContext, float], SleepDecision]
