# tests/test_wrappers.py

import asyncio

import pytest

from redress import AsyncRetryPolicy, RetryPolicy, default_classifier
from redress.config import RetryConfig
from redress.errors import ErrorClass
from redress.testing import RecordingPolicy, instant_retries


def test_retry_policy_attribute_forwarding_and_readonly() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=3,
    )

    assert policy.policy is policy._policy
    assert policy.max_attempts == 3
    policy.max_attempts = 2
    assert policy.max_attempts == 2

    policy.custom_attr = "ok"
    assert policy.custom_attr == "ok"

    with pytest.raises(AttributeError):
        policy.retry = None  # type: ignore[assignment]
    with pytest.raises(AttributeError):
        policy.policy = None  # type: ignore[assignment]


def test_async_retry_policy_attribute_forwarding_and_readonly() -> None:
    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=4,
    )

    assert policy.policy is policy._policy
    assert policy.max_attempts == 4
    policy.max_attempts = 3
    assert policy.max_attempts == 3

    policy.custom_attr = "ok"
    assert policy.custom_attr == "ok"

    with pytest.raises(AttributeError):
        policy.retry = None  # type: ignore[assignment]
    with pytest.raises(AttributeError):
        policy.policy = None  # type: ignore[assignment]


def test_async_retry_policy_from_config() -> None:
    cfg = RetryConfig(deadline_s=5.0, max_attempts=2, default_strategy=instant_retries)
    policy = AsyncRetryPolicy.from_config(cfg, classifier=default_classifier)
    assert policy.policy is policy._policy
    assert policy.max_attempts == 2


def test_retry_config_per_class_limits_copy() -> None:
    cfg = RetryConfig(per_class_max_attempts={ErrorClass.RATE_LIMIT: 1})
    limits = cfg.per_class_limits()
    assert limits == {ErrorClass.RATE_LIMIT: 1}
    limits[ErrorClass.RATE_LIMIT] = 2
    assert cfg.per_class_max_attempts == {ErrorClass.RATE_LIMIT: 1}


def test_retry_policy_forwards_call_kwargs() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=1,
    )

    recorder = RecordingPolicy(policy._policy)
    policy._policy = recorder

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        return None

    def log(event: str, fields: dict[str, object]) -> None:
        return None

    result = policy.call(lambda: "ok", operation="op", on_metric=metric, on_log=log)
    assert result == "ok"

    recorded = recorder.calls[-1]
    assert recorded.kwargs["operation"] == "op"
    assert recorded.kwargs["on_metric"] is metric
    assert recorded.kwargs["on_log"] is log


def test_async_retry_policy_forwards_call_kwargs() -> None:
    policy = AsyncRetryPolicy(
        classifier=default_classifier,
        strategy=instant_retries,
        max_attempts=1,
    )

    recorder = RecordingPolicy(policy._policy)
    policy._policy = recorder

    def metric(event: str, attempt: int, sleep_s: float, tags: dict[str, object]) -> None:
        return None

    def log(event: str, fields: dict[str, object]) -> None:
        return None

    async def run() -> None:
        async def func() -> str:
            return "ok"

        result = await policy.call(func, operation="op", on_metric=metric, on_log=log)
        assert result == "ok"

    asyncio.run(run())

    recorded = recorder.calls[-1]
    assert recorded.kwargs["operation"] == "op"
    assert recorded.kwargs["on_metric"] is metric
    assert recorded.kwargs["on_log"] is log
