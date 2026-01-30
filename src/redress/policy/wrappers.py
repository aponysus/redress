from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from ..budget import Budget
from ..config import ResultClassifierFn, RetryConfig
from ..errors import ErrorClass
from ..sleep import (
    AsyncBeforeSleepHook,
    AsyncSleeperFn,
    BeforeSleepHook,
    SleeperFn,
    SleepFn,
)
from ..strategies import StrategyFn
from .container import AsyncPolicy, Policy
from .retry import AsyncRetry, Retry
from .types import (
    AbortPredicate,
    AttemptHook,
    ClassifierFn,
    LogHook,
    MetricHook,
    RetryOutcome,
    RetryTimeline,
    T,
)


class RetryPolicy:
    """
    Backward-compatible sugar for Policy(retry=Retry(...)).
    """

    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        result_classifier: ResultClassifierFn | None = None,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | None = None,
        sleeper: SleeperFn | None = None,
        budget: Budget | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        self._policy = Policy(
            retry=Retry(
                classifier=classifier,
                result_classifier=result_classifier,
                strategy=strategy,
                strategies=strategies,
                sleep=sleep,
                before_sleep=before_sleep,
                sleeper=sleeper,
                budget=budget,
                deadline_s=deadline_s,
                max_attempts=max_attempts,
                max_unknown_attempts=max_unknown_attempts,
                per_class_max_attempts=per_class_max_attempts,
            )
        )

    @classmethod
    def from_config(
        cls,
        config: RetryConfig,
        *,
        classifier: ClassifierFn,
    ) -> "RetryPolicy":
        """
        Construct a RetryPolicy from a RetryConfig bundle.
        """
        return cls(
            classifier=classifier,
            result_classifier=config.result_classifier,
            strategy=config.default_strategy,
            strategies=config.class_strategies,
            sleep=config.sleep,
            before_sleep=cast(BeforeSleepHook | None, config.before_sleep),
            sleeper=cast(SleeperFn | None, config.sleeper),
            budget=config.budget,
            deadline_s=config.deadline_s,
            max_attempts=config.max_attempts,
            max_unknown_attempts=config.max_unknown_attempts,
            per_class_max_attempts=config.per_class_max_attempts,
        )

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def retry(self) -> Retry:
        retry = self._policy.retry
        if retry is None:
            raise AttributeError("RetryPolicy has no retry component configured.")
        return retry

    def call(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | None = None,
        sleeper: SleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> Any:
        return self._policy.call(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
        )

    def execute(
        self,
        func: Callable[[], Any],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | None = None,
        sleeper: SleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
        capture_timeline: bool | RetryTimeline | None = None,
    ) -> RetryOutcome[Any]:
        return self._policy.execute(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
            capture_timeline=capture_timeline,
        )

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | None = None,
        sleeper: SleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> Any:
        return self._policy.context(
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.retry, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_policy":
            object.__setattr__(self, name, value)
            return
        if name in {"policy", "retry"}:
            raise AttributeError(f"{name} is read-only.")
        policy = self.__dict__.get("_policy")
        if policy is not None and policy.retry is not None and hasattr(policy.retry, name):
            setattr(policy.retry, name, value)
            return
        object.__setattr__(self, name, value)


class AsyncRetryPolicy:
    """
    Backward-compatible sugar for AsyncPolicy(retry=AsyncRetry(...)).
    """

    def __init__(
        self,
        *,
        classifier: ClassifierFn,
        result_classifier: ResultClassifierFn | None = None,
        strategy: StrategyFn | None = None,
        strategies: Mapping[ErrorClass, StrategyFn] | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        budget: Budget | None = None,
        deadline_s: float = 60.0,
        max_attempts: int = 6,
        max_unknown_attempts: int | None = 2,
        per_class_max_attempts: Mapping[ErrorClass, int] | None = None,
    ) -> None:
        self._policy = AsyncPolicy(
            retry=AsyncRetry(
                classifier=classifier,
                result_classifier=result_classifier,
                strategy=strategy,
                strategies=strategies,
                sleep=sleep,
                before_sleep=before_sleep,
                sleeper=sleeper,
                budget=budget,
                deadline_s=deadline_s,
                max_attempts=max_attempts,
                max_unknown_attempts=max_unknown_attempts,
                per_class_max_attempts=per_class_max_attempts,
            )
        )

    @classmethod
    def from_config(
        cls,
        config: RetryConfig,
        *,
        classifier: ClassifierFn,
    ) -> "AsyncRetryPolicy":
        """
        Construct an AsyncRetryPolicy from a RetryConfig bundle.
        """
        return cls(
            classifier=classifier,
            result_classifier=config.result_classifier,
            strategy=config.default_strategy,
            strategies=config.class_strategies,
            sleep=config.sleep,
            before_sleep=config.before_sleep,
            sleeper=config.sleeper,
            budget=config.budget,
            deadline_s=config.deadline_s,
            max_attempts=config.max_attempts,
            max_unknown_attempts=config.max_unknown_attempts,
            per_class_max_attempts=config.per_class_max_attempts,
        )

    @property
    def policy(self) -> AsyncPolicy:
        return self._policy

    @property
    def retry(self) -> AsyncRetry:
        retry = self._policy.retry
        if retry is None:
            raise AttributeError("AsyncRetryPolicy has no retry component configured.")
        return retry

    async def call(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> T:
        return await self._policy.call(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
        )

    async def execute(
        self,
        func: Callable[[], Awaitable[T]],
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
        capture_timeline: bool | RetryTimeline | None = None,
    ) -> RetryOutcome[T]:
        return await self._policy.execute(
            func,
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
            capture_timeline=capture_timeline,
        )

    def context(
        self,
        *,
        on_metric: MetricHook | None = None,
        on_log: LogHook | None = None,
        operation: str | None = None,
        abort_if: AbortPredicate | None = None,
        sleep: SleepFn | None = None,
        before_sleep: BeforeSleepHook | AsyncBeforeSleepHook | None = None,
        sleeper: SleeperFn | AsyncSleeperFn | None = None,
        on_attempt_start: AttemptHook | None = None,
        on_attempt_end: AttemptHook | None = None,
    ) -> Any:
        return self._policy.context(
            on_metric=on_metric,
            on_log=on_log,
            operation=operation,
            abort_if=abort_if,
            sleep=sleep,
            before_sleep=before_sleep,
            sleeper=sleeper,
            on_attempt_start=on_attempt_start,
            on_attempt_end=on_attempt_end,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.retry, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_policy":
            object.__setattr__(self, name, value)
            return
        if name in {"policy", "retry"}:
            raise AttributeError(f"{name} is read-only.")
        policy = self.__dict__.get("_policy")
        if policy is not None and policy.retry is not None and hasattr(policy.retry, name):
            setattr(policy.retry, name, value)
            return
        object.__setattr__(self, name, value)
