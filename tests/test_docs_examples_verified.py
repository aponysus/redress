from __future__ import annotations

import asyncio
import re
import runpy
from pathlib import Path

import pytest

from redress import ErrorClass, Policy, Retry, StopReason
from redress.policy import retry_helpers
from redress.testing import instant_retries


def _snippet_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "snippets" / name


async def _no_async_sleep(_: float) -> None:
    return None


def _no_sleep(_: float) -> None:
    return None


def test_async_worker_retry_snippet_smoke(monkeypatch, capsys) -> None:
    monkeypatch.setattr(retry_helpers.asyncio, "sleep", _no_async_sleep)
    namespace = runpy.run_path(str(_snippet_path("async_worker_retry.py")))
    monkeypatch.setattr(namespace["asyncio"], "sleep", _no_async_sleep)

    asyncio.run(namespace["main"]())

    output = capsys.readouterr().out
    assert "processed ok" in output
    assert "processed flaky" in output


def test_async_worker_abort_snippet_smoke(monkeypatch, capsys) -> None:
    monkeypatch.setattr(retry_helpers.asyncio, "sleep", _no_async_sleep)
    namespace = runpy.run_path(str(_snippet_path("async_worker_abort.py")))
    shutdown = asyncio.Event()
    shutdown.set()

    asyncio.run(namespace["worker_loop"](["ok", "flaky"], shutdown))

    output = capsys.readouterr().out
    assert "shutdown requested, stopping worker" in output


def test_bench_retry_snippet_smoke() -> None:
    namespace = runpy.run_path(str(_snippet_path("bench_retry.py")))

    namespace["bench_success"](loop_count=3)
    namespace["bench_single_retry"](loop_count=3)


def test_decorator_retry_snippet_smoke(monkeypatch, capsys) -> None:
    monkeypatch.setattr(retry_helpers.time, "sleep", _no_sleep)
    monkeypatch.setattr(retry_helpers.asyncio, "sleep", _no_async_sleep)
    namespace = runpy.run_path(str(_snippet_path("decorator_retry.py")))
    monkeypatch.setattr(namespace["asyncio"], "sleep", _no_async_sleep)

    namespace["main"]()

    output = capsys.readouterr().out
    assert "Sync: sync-ok" in output
    assert "Async: async-ok" in output


def _guide_examples(name: str) -> list[str]:
    path = Path(__file__).resolve().parents[1] / "docs" / name
    return [
        code
        for code in re.findall(r"```python\n(.*?)```", path.read_text(), re.DOTALL)
        if "from redress import" in code
    ]


@pytest.mark.parametrize(
    "guide",
    [
        "migrating-from-tenacity.md",
        "migrating-from-backoff.md",
        "performance-tuning.md",
        "troubleshooting.md",
    ],
)
def test_evergreen_guide_examples(guide, monkeypatch) -> None:
    monkeypatch.setattr(retry_helpers.time, "sleep", _no_sleep)
    examples = _guide_examples(guide)
    assert examples, f"No executable Redress examples in {guide}"
    for code in examples:
        exec(compile(code, guide, "exec"), {})


@pytest.mark.parametrize("guide", ["migrating-from-tenacity.md", "migrating-from-backoff.md"])
def test_migration_classifier_preserves_exception_selection(guide) -> None:
    namespace = {}
    exec(compile(_guide_examples(guide)[0], guide, "exec"), namespace)
    classifier = namespace["classify_timeout"]
    policy = Policy(
        retry=Retry(
            classifier=classifier,
            strategy=instant_retries,
            max_attempts=5,
        )
    )

    def timeout():
        raise TimeoutError("unavailable")

    outcome = policy.execute(timeout)
    assert outcome.attempts == 5
    assert outcome.last_class is ErrorClass.TRANSIENT
    assert outcome.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL

    def excluded_exception():
        raise ValueError("invalid input")

    outcome = policy.execute(excluded_exception)
    assert outcome.attempts == 1
    assert outcome.stop_reason is StopReason.NON_RETRYABLE_CLASS
