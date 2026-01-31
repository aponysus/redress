import asyncio

import pytest

from redress.circuit import CircuitState
from redress.classify import Classification
from redress.errors import ErrorClass, StopReason
from redress.policy.types import RetryOutcome
from redress.strategies import BackoffContext
from redress.testing import (
    BreakerDecision,
    DeterministicStrategy,
    FakeCircuitBreaker,
    FakePolicy,
    RecordingPolicy,
    instant_retries,
    no_retries,
)


def _context(attempt: int) -> BackoffContext:
    return BackoffContext(
        attempt=attempt,
        classification=Classification(ErrorClass.TRANSIENT),
        prev_sleep_s=None,
        remaining_s=None,
        cause="exception",
    )


def test_deterministic_strategy_sequence() -> None:
    strat = DeterministicStrategy([0.1, 0.2], default=0.5)

    assert strat(_context(1)) == 0.1
    assert strat(_context(2)) == 0.2
    assert strat(_context(3)) == 0.5
    assert len(strat.calls) == 3

    strat.reset()
    assert strat.calls == []


def test_instant_retries() -> None:
    assert instant_retries(_context(1)) == 0.0


def test_no_retries_config() -> None:
    cfg = no_retries(deadline_s=12.0, attempt_timeout_s=0.25)

    assert cfg.deadline_s == 12.0
    assert cfg.attempt_timeout_s == 0.25
    assert cfg.max_attempts == 1
    assert cfg.max_unknown_attempts == 0
    assert cfg.default_strategy is instant_retries


def test_fake_policy_call_and_execute() -> None:
    policy = FakePolicy(call_result="ok")
    assert policy.call(lambda: "ignored") == "ok"
    assert policy.calls[-1].result == "ok"

    outcome = policy.execute(lambda: "ignored")
    assert outcome.ok is True
    assert outcome.value == "ok"
    assert policy.executions[-1].outcome is outcome


def test_fake_policy_execute_error() -> None:
    exc = TimeoutError("boom")
    policy = FakePolicy(call_error=exc)

    outcome = policy.execute(lambda: "ignored")
    assert outcome.ok is False
    assert outcome.stop_reason is StopReason.MAX_ATTEMPTS_GLOBAL
    assert outcome.last_exception is exc
    assert outcome.last_class is ErrorClass.TRANSIENT


def test_fake_policy_call_error() -> None:
    policy = FakePolicy(call_error=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        policy.call(lambda: "ignored")

    assert isinstance(policy.calls[-1].exception, RuntimeError)


def test_recording_policy_records_sync_calls() -> None:
    inner = FakePolicy(call_result="ok")
    policy = RecordingPolicy(inner)

    assert policy.call(lambda: "ignored") == "ok"
    assert policy.calls[-1].result == "ok"

    outcome = policy.execute(lambda: "ignored")
    assert policy.executions[-1].outcome is outcome


def test_recording_policy_records_async_calls() -> None:
    class AsyncPolicy:
        async def call(self, func, **kwargs):
            return await func()

        async def execute(self, func, **kwargs):
            return await func()

    policy = RecordingPolicy(AsyncPolicy())

    async def run() -> None:
        async def func() -> str:
            return "ok"

        async def outcome_func() -> RetryOutcome[str]:
            return RetryOutcome(
                ok=True,
                value="ok",
                stop_reason=None,
                attempts=1,
                last_class=None,
                last_exception=None,
                last_result=None,
                cause=None,
                elapsed_s=0.0,
            )

        assert await policy.call(func) == "ok"
        assert policy.calls[-1].result == "ok"

        outcome = await policy.execute(outcome_func)
        assert policy.executions[-1].outcome is outcome

    asyncio.run(run())


def test_fake_circuit_breaker_sequence() -> None:
    breaker = FakeCircuitBreaker(
        state=CircuitState.OPEN,
        allow_sequence=[
            BreakerDecision(False, CircuitState.OPEN, "circuit_rejected"),
            BreakerDecision(True, CircuitState.HALF_OPEN, "circuit_half_open"),
        ],
        success_event="circuit_closed",
        failure_event="circuit_opened",
    )

    decision = breaker.allow()
    assert decision.allowed is False
    assert decision.state is CircuitState.OPEN
    assert breaker.allow_calls == 1

    decision = breaker.allow()
    assert decision.allowed is True
    assert decision.state is CircuitState.HALF_OPEN
    assert breaker.allow_calls == 2

    assert breaker.record_failure(ErrorClass.TRANSIENT) == "circuit_opened"
    assert breaker.record_failure_calls == [ErrorClass.TRANSIENT]

    assert breaker.record_success() == "circuit_closed"
    assert breaker.record_success_calls == 1

    breaker.push_decision(BreakerDecision(True, CircuitState.CLOSED))
    decision = breaker.allow()
    assert decision.allowed is True
    assert decision.state is CircuitState.CLOSED
