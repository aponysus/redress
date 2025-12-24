"""
Minimal decorator-based retry examples (sync + async).
"""

import asyncio
from collections.abc import Iterator

from redress import retry
from redress.classify import default_classifier
from redress.strategies import decorrelated_jitter


def _flaky_sequence() -> Iterator[int]:
    """
    Yield two failures then success.
    """
    yield from [0, 0, 1]


flaky_values = _flaky_sequence()
flaky_async_values = _flaky_sequence()


@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=0.5),
)
def flaky_sync() -> str:
    if next(flaky_values) == 0:
        raise RuntimeError("boom")
    return "sync-ok"


@retry(
    classifier=default_classifier,
    strategy=decorrelated_jitter(max_s=0.5),
)
async def flaky_async() -> str:
    if next(flaky_async_values) == 0:
        raise RuntimeError("boom")
    return "async-ok"


def main() -> None:
    print("Sync:", flaky_sync())
    print("Async:", asyncio.run(flaky_async()))


if __name__ == "__main__":
    main()
