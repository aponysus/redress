from collections.abc import Awaitable, Callable
from enum import Enum

from .strategies import BackoffContext


class SleepDecision(str, Enum):
    SLEEP = "sleep"
    DEFER = "defer"
    ABORT = "abort"


SleepFn = Callable[[BackoffContext, float], SleepDecision]
BeforeSleepHook = Callable[[BackoffContext, float], None]
AsyncBeforeSleepHook = Callable[[BackoffContext, float], Awaitable[None]]
SleeperFn = Callable[[float], None]
AsyncSleeperFn = Callable[[float], Awaitable[None]]
