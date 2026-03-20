from collections.abc import Mapping

import redress.contrib.sentry as sentry


class _FakeSentry:
    def __init__(self) -> None:
        self.breadcrumbs: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []

    def add_breadcrumb(
        self,
        *,
        category: str,
        message: str,
        level: str,
        data: Mapping[str, object] | None = None,
    ) -> None:
        self.breadcrumbs.append(
            {
                "category": category,
                "message": message,
                "level": level,
                "data": dict(data or {}),
            }
        )

    def capture_message(self, message: str, *, level: str = "error") -> None:
        self.messages.append({"message": message, "level": level})


def test_sentry_hooks_add_breadcrumbs_and_capture_terminal_failures() -> None:
    client = _FakeSentry()
    hooks = sentry.sentry_hooks(sentry=client)
    on_log = hooks["on_log"]

    on_log("retry", {"attempt": 1, "sleep_s": 0.5, "class": "RATE_LIMIT", "operation": "fetch"})
    on_log(
        "max_attempts_exceeded",
        {
            "attempt": 3,
            "sleep_s": 0.0,
            "class": "RATE_LIMIT",
            "operation": "fetch",
            "stop_reason": "MAX_ATTEMPTS_GLOBAL",
        },
    )

    assert client.breadcrumbs == [
        {
            "category": "redress",
            "message": "retry",
            "level": "warning",
            "data": {
                "attempt": 1,
                "sleep_s": 0.5,
                "class": "RATE_LIMIT",
                "operation": "fetch",
            },
        },
        {
            "category": "redress",
            "message": "max_attempts_exceeded",
            "level": "error",
            "data": {
                "attempt": 3,
                "sleep_s": 0.0,
                "class": "RATE_LIMIT",
                "operation": "fetch",
                "stop_reason": "MAX_ATTEMPTS_GLOBAL",
            },
        },
    ]
    assert client.messages == [{"message": "redress.max_attempts_exceeded", "level": "error"}]


def test_sentry_default_import(monkeypatch) -> None:
    client = _FakeSentry()
    monkeypatch.setattr(sentry.importlib, "import_module", lambda name: client)
    hooks = sentry.sentry_hooks()
    hooks["on_log"]("success", {"attempt": 1, "operation": "fetch"})

    assert client.breadcrumbs == [
        {
            "category": "redress",
            "message": "success",
            "level": "info",
            "data": {"attempt": 1, "operation": "fetch"},
        }
    ]
    assert client.messages == []


def test_sentry_public_exports_stable() -> None:
    assert sentry.__all__ == [
        "SentryHooks",
        "SentrySdk",
        "sentry_hooks",
    ]
