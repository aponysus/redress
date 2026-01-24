# tests/test_wrappers.py

import pytest

from redress import AsyncRetryPolicy, RetryPolicy, default_classifier
from redress.config import RetryConfig
from redress.errors import ErrorClass


def _no_sleep_strategy(_: int, __: ErrorClass, ___: float | None) -> float:
    return 0.0


def test_retry_policy_attribute_forwarding_and_readonly() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=_no_sleep_strategy,
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
        strategy=_no_sleep_strategy,
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
    cfg = RetryConfig(deadline_s=5.0, max_attempts=2, default_strategy=_no_sleep_strategy)
    policy = AsyncRetryPolicy.from_config(cfg, classifier=default_classifier)
    assert policy.policy is policy._policy
    assert policy.max_attempts == 2


def test_retry_config_per_class_limits_copy() -> None:
    cfg = RetryConfig(per_class_max_attempts={ErrorClass.RATE_LIMIT: 1})
    limits = cfg.per_class_limits()
    assert limits == {ErrorClass.RATE_LIMIT: 1}
    limits[ErrorClass.RATE_LIMIT] = 2
    assert cfg.per_class_max_attempts == {ErrorClass.RATE_LIMIT: 1}
