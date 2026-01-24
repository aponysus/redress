from collections.abc import Mapping
from datetime import timedelta

from ..classify import Classification
from ..config import ResultClassifierFn
from ..errors import ErrorClass
from ..strategies import BackoffFn, StrategyFn, _normalize_strategy
from .types import ClassifierFn


class _BaseRetryPolicy:
    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        result_classifier: ResultClassifierFn | None = None,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        if strategies is None and strategy is None:
            raise ValueError(
                "Retry requires either a default 'strategy' or a " "'strategies' mapping (or both)."
            )

        self.classifier: ClassifierFn = classifier
        self.result_classifier: ResultClassifierFn | None = result_classifier
        self._strategies: dict[ErrorClass, BackoffFn] = {
            klass: _normalize_strategy(fn) for klass, fn in (strategies or {}).items()
        }
        self._default_strategy: BackoffFn | None = (
            _normalize_strategy(strategy) if strategy is not None else None
        )
        self.deadline: timedelta = timedelta(seconds=deadline_s)
        self.max_attempts: int = max_attempts
        self.max_unknown_attempts: int | None = max_unknown_attempts
        self.per_class_max_attempts: dict[ErrorClass, int] = dict(per_class_max_attempts or {})

    def _select_strategy(self, klass: ErrorClass) -> BackoffFn | None:
        return self._strategies.get(klass, self._default_strategy)


def _normalize_classification(result: ErrorClass | Classification) -> Classification:
    if isinstance(result, Classification):
        return result
    return Classification(klass=result)
