import redress.budget as _budget_mod
from redress import Budget


def test_budget_consumes_and_resets(monkeypatch) -> None:
    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr(_budget_mod.time, "monotonic", fake_monotonic)

    budget = Budget(max_retries=2, window_s=10.0)
    assert budget.consume() is True
    assert budget.consume() is True
    assert budget.consume() is False

    now = 10.1
    assert budget.consume() is True
