from __future__ import annotations

import asyncio
import runpy
from pathlib import Path

from redress.policy import retry_helpers


def _snippet_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "snippets" / name


async def _no_async_sleep(_: float) -> None:
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
