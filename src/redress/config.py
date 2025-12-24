from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ErrorClass
from .strategies import StrategyFn


@dataclass
class RetryConfig:
    deadline_s: float = 60.0
    max_attempts: int = 6
    max_unknown_attempts: int | None = 2
    per_class_max_attempts: Mapping[ErrorClass, int] | None = None

    default_strategy: StrategyFn | None = None
    class_strategies: Mapping[ErrorClass, StrategyFn] | None = None

    def per_class_limits(self) -> dict[ErrorClass, int]:
        """
        Return a mutable copy of per-class limits for safe mutation downstream.
        """
        return dict(self.per_class_max_attempts or {})
