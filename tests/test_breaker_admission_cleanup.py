"""A policy exit must settle only its own circuit-breaker admission."""

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest

from redress import (
    AsyncPolicy,
    AsyncRetry,
    CircuitBreaker,
    CircuitState,
    ErrorClass,
    Policy,
    Retry,
    default_classifier,
)


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def ready_breaker() -> tuple[Clock, CircuitBreaker]:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0, clock=clock)
    breaker.record_failure(ErrorClass.TRANSIENT)
    clock.now = 2.0
    return clock, breaker


def make_policy(
    asynchronous: bool, breaker: CircuitBreaker, with_retry: bool = True, **options: Any
) -> Any:
    config = dict(classifier=default_classifier, strategy=lambda _ctx: 0.0, max_attempts=2)
    config.update(options)
    policy_type = AsyncPolicy if asynchronous else Policy
    retry_type = AsyncRetry if asynchronous else Retry
    return policy_type(retry=retry_type(**config) if with_retry else None, circuit_breaker=breaker)


def invoke(policy: Any, surface: str, operation: Callable[[], Any], **kwargs: Any) -> Any:
    """Capture process-exit exceptions inside the event loop as well as sync calls."""
    if isinstance(policy, AsyncPolicy):

        async def run() -> Any:
            async def async_operation() -> Any:
                return operation()

            try:
                return await getattr(policy, surface)(async_operation, **kwargs)
            except BaseException as exc:
                return exc

        return asyncio.run(run())
    try:
        return getattr(policy, surface)(operation, **kwargs)
    except BaseException as exc:
        return exc


@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize(
    ("stage", "with_retry"),
    [("operation", False), ("operation", True), ("sleeper", True), ("before_sleep", True)],
)
def test_cancelled_task_releases_probe(surface: str, stage: str, with_retry: bool) -> None:
    _, breaker = ready_breaker()

    async def run() -> None:
        entered = asyncio.Event()
        blocked = asyncio.Event()

        async def wait(*args: Any) -> None:
            entered.set()
            await blocked.wait()

        async def operation() -> None:
            if stage == "operation":
                await wait()
            else:
                raise ConnectionError("retryable operation failure")

        policy = make_policy(True, breaker, with_retry)
        kwargs = {stage: wait} if stage != "operation" else {}
        task = asyncio.create_task(getattr(policy, surface)(operation, **kwargs))
        waiter = asyncio.create_task(entered.wait())
        try:
            await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
            assert entered.is_set(), "operation exited before reaching the cancellation point"
            assert not breaker.allow().allowed
            task.cancel("cancel this probe")
            with pytest.raises(asyncio.CancelledError) as caught:
                await task
            assert caught.value.args == ("cancel this probe",)
            assert breaker.state is CircuitState.HALF_OPEN

            async def recovered() -> str:
                return "recovered"

            outcome = await AsyncPolicy(circuit_breaker=breaker).execute(recovered)
            assert outcome.ok and outcome.value == "recovered"
            assert breaker.state is CircuitState.CLOSED
        finally:
            task.cancel()
            waiter.cancel()
            await asyncio.gather(task, waiter, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("asynchronous", "error_type"),
    [(True, asyncio.CancelledError), (False, KeyboardInterrupt), (False, SystemExit)],
)
@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
@pytest.mark.parametrize(
    "stage", ["operation", "on_attempt_start", "on_attempt_end", "on_log", "on_metric"]
)
def test_control_flow_exceptions_release_admission(
    asynchronous: bool, error_type: type[BaseException], surface: str, with_retry: bool, stage: str
) -> None:
    _, breaker = ready_breaker()
    error = error_type("stop this execution")

    def interrupt(*args: Any) -> Any:
        raise error

    policy = make_policy(asynchronous, breaker, with_retry)
    operation = interrupt if stage == "operation" else lambda: "ok"
    kwargs = {stage: interrupt} if stage != "operation" else {}
    assert invoke(policy, surface, operation, **kwargs) is error
    assert breaker.allow().allowed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("stage", ["classifier", "strategy", "abort_if", "sleep", "sleeper"])
def test_retry_processing_exception_does_not_strand_probe(
    asynchronous: bool, surface: str, stage: str
) -> None:
    clock, breaker = ready_breaker()
    error = RuntimeError("retry processing failed")

    def fail(*args: Any) -> Any:
        raise error

    def operation() -> None:
        raise ConnectionError("operation failed")

    options = {stage: lambda ctx: fail(ctx)} if stage in {"classifier", "strategy"} else {}
    kwargs = {} if options else {stage: fail}
    policy = make_policy(asynchronous, breaker, **options)
    assert invoke(policy, surface, operation, **kwargs) is error
    # call() may classify an escaping ordinary exception as a final failure.
    # In either case recovery must be possible after the normal recovery timeout.
    clock.now = 1000.0
    assert breaker.allow().allowed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
def test_preflight_abort_and_rejection_do_not_release_another_probe(
    asynchronous: bool, surface: str, with_retry: bool
) -> None:
    _, breaker = ready_breaker()
    assert breaker.allow().allowed
    policy = make_policy(asynchronous, breaker, with_retry)

    def unexpected() -> None:
        pytest.fail("the second operation must not run")

    invoke(policy, surface, unexpected, abort_if=lambda: True)
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow().allowed
    invoke(policy, surface, unexpected)
    assert not breaker.allow().allowed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
@pytest.mark.parametrize("completion", ["success", "failure", "cancel"])
@pytest.mark.parametrize("was_probe", [False, True])
def test_previous_execution_cannot_resolve_current_probe(
    asynchronous: bool, surface: str, with_retry: bool, completion: str, was_probe: bool
) -> None:
    if was_probe:
        clock, breaker = ready_breaker()
    else:
        clock = Clock()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0, clock=clock)
    policy = make_policy(asynchronous, breaker, with_retry, max_attempts=1)

    def old_operation() -> str:
        if was_probe:
            # Manual cancellation allows replacement without a state transition.
            breaker.record_cancel()
        else:
            breaker.record_failure(ErrorClass.TRANSIENT)
        clock.now += 2.0
        assert breaker.allow().allowed
        if completion == "cancel":
            raise asyncio.CancelledError("old execution")
        if completion == "failure":
            raise ConnectionError("old execution")
        return "old success"

    invoke(policy, surface, old_operation)
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow().allowed
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
def test_old_failure_does_not_reopen_a_recovered_circuit(
    asynchronous: bool, surface: str, with_retry: bool
) -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0, clock=clock)

    def old_operation() -> None:
        breaker.record_failure(ErrorClass.TRANSIENT)
        clock.now = 2.0
        assert breaker.allow().allowed
        breaker.record_success()
        raise ConnectionError("failure from before recovery")

    policy = make_policy(asynchronous, breaker, with_retry, max_attempts=1)
    invoke(policy, surface, old_operation)
    assert breaker.state is CircuitState.CLOSED


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("surface", ["call", "execute"])
def test_terminal_callback_cannot_release_a_later_probe(asynchronous: bool, surface: str) -> None:
    clock, breaker = ready_breaker()
    error = asyncio.CancelledError("after completion")

    def on_log(event: str, fields: dict[str, Any]) -> None:
        if event == "circuit_closed":
            breaker.record_failure(ErrorClass.TRANSIENT)
            clock.now += 2.0
            assert breaker.allow().allowed
            raise error

    policy = make_policy(asynchronous, breaker)
    assert invoke(policy, surface, lambda: "ok", on_log=on_log) is error
    assert breaker.state is CircuitState.HALF_OPEN
    assert not breaker.allow().allowed


@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
def test_cancelling_older_async_task_leaves_active_probe_owned(
    surface: str, with_retry: bool
) -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0, clock=clock)
    policy = make_policy(True, breaker, with_retry, max_attempts=1)

    async def run() -> None:
        old_started = asyncio.Event()
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()

        async def old_operation() -> None:
            old_started.set()
            await asyncio.Event().wait()

        async def probe_operation() -> str:
            probe_started.set()
            await release_probe.wait()
            return "probe recovered"

        old = asyncio.create_task(getattr(policy, surface)(old_operation))
        probe = None
        try:
            await old_started.wait()
            breaker.record_failure(ErrorClass.TRANSIENT)
            clock.now = 2.0
            probe = asyncio.create_task(getattr(policy, surface)(probe_operation))
            await probe_started.wait()
            old.cancel("old execution")
            with pytest.raises(asyncio.CancelledError):
                await old
            assert not probe.done()
            assert breaker.state is CircuitState.HALF_OPEN
            assert not breaker.allow().allowed
            release_probe.set()
            result = await probe
            assert (result.value if surface == "execute" else result) == "probe recovered"
            assert breaker.state is CircuitState.CLOSED
        finally:
            old.cancel()
            if probe is not None:
                probe.cancel()
            await asyncio.gather(
                old, *([probe] if probe is not None else []), return_exceptions=True
            )

    asyncio.run(run())


@pytest.mark.parametrize("surface", ["call", "execute"])
@pytest.mark.parametrize("with_retry", [False, True])
def test_interrupted_older_thread_leaves_active_probe_owned(surface: str, with_retry: bool) -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=1.0, clock=clock)
    policy = make_policy(False, breaker, with_retry, max_attempts=1)
    old_started, release_old = threading.Event(), threading.Event()
    probe_started, release_probe = threading.Event(), threading.Event()
    error = SystemExit("old execution")

    def old_operation() -> None:
        old_started.set()
        assert release_old.wait(timeout=5)
        raise error

    def probe_operation() -> str:
        probe_started.set()
        assert release_probe.wait(timeout=5)
        return "probe recovered"

    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            old = pool.submit(invoke, policy, surface, old_operation)
            assert old_started.wait(timeout=5)
            breaker.record_failure(ErrorClass.TRANSIENT)
            clock.now = 2.0
            probe = pool.submit(invoke, policy, surface, probe_operation)
            assert probe_started.wait(timeout=5)
            release_old.set()
            assert old.result(timeout=5) is error
            assert not probe.done()
            assert breaker.state is CircuitState.HALF_OPEN
            assert not breaker.allow().allowed
            release_probe.set()
            result = probe.result(timeout=5)
            assert (result.value if surface == "execute" else result) == "probe recovered"
            assert breaker.state is CircuitState.CLOSED
        finally:
            release_old.set()
            release_probe.set()
