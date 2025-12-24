"""
Pyperf microbenchmarks for redress retry overhead (no real sleeping).

Usage:
    uv pip install .[dev]
    uv run python docs/snippets/bench_retry.py
"""

import pyperf

from redress import RetryPolicy, default_classifier
from redress.errors import ErrorClass
from redress.strategies import decorrelated_jitter


def make_policy() -> RetryPolicy:
    return RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=0.0),  # no real sleep
        max_attempts=3,
    )


def bench_success(loop_count: int = 1000) -> None:
    policy = make_policy()

    def func() -> int:
        return 1

    for _ in range(loop_count):
        policy.call(func)


def bench_single_retry(loop_count: int = 1000) -> None:
    policy = make_policy()
    calls = {"n": 0}

    class TransientError(Exception):
        pass

    def classifier(exc: BaseException) -> ErrorClass:
        return ErrorClass.TRANSIENT

    policy.classifier = classifier

    def func() -> int:
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            raise TransientError()
        return 1

    for _ in range(loop_count):
        try:
            policy.call(func)
        except TransientError:
            pass


def main() -> None:
    runner = pyperf.Runner()
    runner.bench_func("retry_success", bench_success)
    runner.bench_func("retry_single_retry", bench_single_retry)


if __name__ == "__main__":
    main()
