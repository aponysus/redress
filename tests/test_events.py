from redress.events import EventName


def test_event_name_values_are_stable() -> None:
    assert EventName.SUCCESS.value == "success"
    assert EventName.RETRY.value == "retry"
    assert EventName.PERMANENT_FAIL.value == "permanent_fail"
    assert EventName.DEADLINE_EXCEEDED.value == "deadline_exceeded"
    assert EventName.MAX_ATTEMPTS_EXCEEDED.value == "max_attempts_exceeded"
    assert EventName.MAX_UNKNOWN_ATTEMPTS_EXCEEDED.value == "max_unknown_attempts_exceeded"
    assert EventName.NO_STRATEGY_CONFIGURED.value == "no_strategy_configured"
    assert EventName.ABORTED.value == "aborted"
    assert EventName.CIRCUIT_OPENED.value == "circuit_opened"
    assert EventName.CIRCUIT_HALF_OPEN.value == "circuit_half_open"
    assert EventName.CIRCUIT_CLOSED.value == "circuit_closed"
    assert EventName.CIRCUIT_REJECTED.value == "circuit_rejected"
