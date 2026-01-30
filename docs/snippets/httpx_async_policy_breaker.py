"""
Async demo: unified AsyncPolicy with Retry-After result retries and circuit breaking.

Run with:
    uv pip install httpx
    uv run python docs/snippets/httpx_async_policy_breaker.py
"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

import httpx

from redress import (
    AsyncPolicy,
    AsyncRetry,
    CircuitBreaker,
    Classification,
    ErrorClass,
    RetryOutcome,
    RetryTimeline,
    default_classifier,
)
from redress.strategies import decorrelated_jitter, retry_after_or


class DemoHandler(BaseHTTPRequestHandler):
    rate_count = 0
    boom_count = 0

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler hook name
        path = self.path.split("?", 1)[0]
        if path == "/rate":
            DemoHandler.rate_count += 1
            if DemoHandler.rate_count < 3:
                self.send_response(429)
                self.send_header("Retry-After", "0.2")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path == "/boom":
            DemoHandler.boom_count += 1
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        return


def start_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def classify_result(resp: httpx.Response) -> ErrorClass | Classification | None:
    status = resp.status_code
    if status == 429:
        retry_after_s = parse_retry_after(resp.headers.get("Retry-After"))
        return Classification(klass=ErrorClass.RATE_LIMIT, retry_after_s=retry_after_s)
    if status >= 500:
        return ErrorClass.SERVER_ERROR
    return None


def build_policy() -> AsyncPolicy:
    retry = AsyncRetry(
        classifier=default_classifier,  # exception classifier
        result_classifier=classify_result,  # response classifier (e.g., 429/5xx)
        strategy=retry_after_or(decorrelated_jitter(max_s=0.5)),
        deadline_s=3.0,
        max_attempts=3,
    )
    breaker = CircuitBreaker(
        failure_threshold=2,
        window_s=5.0,
        recovery_timeout_s=0.6,
        trip_on={ErrorClass.SERVER_ERROR},
    )
    return AsyncPolicy(retry=retry, circuit_breaker=breaker)


def log_event(event: str, fields: Mapping[str, object]) -> None:
    if not event.startswith("circuit_"):
        return
    state = fields.get("state", "-")
    klass = fields.get("class", "-")
    operation = fields.get("operation", "-")
    print(f"[breaker] event={event} state={state} class={klass} op={operation}")


def print_timeline(timeline: RetryTimeline) -> None:
    if not timeline.events:
        print("  timeline: (none)")
        return
    print("  timeline:")
    for event in timeline.events:
        parts = [
            f"attempt={event.attempt}",
            f"event={event.event}",
            f"sleep_s={event.sleep_s:.3f}",
        ]
        if event.error_class is not None:
            parts.append(f"class={event.error_class.name}")
        if event.cause is not None:
            parts.append(f"cause={event.cause}")
        if event.stop_reason is not None:
            parts.append(f"stop={event.stop_reason.value}")
        print(f"  - {' '.join(parts)}")


def print_outcome(
    label: str,
    outcome: RetryOutcome[httpx.Response],
    breaker_state: str,
    timeline: RetryTimeline,
) -> None:
    response = outcome.value if outcome.ok else None
    status = response.status_code if response is not None else None
    stop_reason = outcome.stop_reason.value if outcome.stop_reason is not None else "-"
    last_class = outcome.last_class.name if outcome.last_class is not None else "-"
    last_exc = type(outcome.last_exception).__name__ if outcome.last_exception is not None else "-"
    print(f"\n=== {label} ===")
    print(
        "ok={ok} status={status} attempts={attempts} stop_reason={stop} last_class={klass} last_exc={exc} elapsed_s={elapsed:.3f} breaker={breaker}".format(
            ok=outcome.ok,
            status=status,
            attempts=outcome.attempts,
            stop=stop_reason,
            klass=last_class,
            exc=last_exc,
            elapsed=outcome.elapsed_s,
            breaker=breaker_state,
        )
    )
    print_timeline(timeline)


async def run_case(policy: AsyncPolicy, client: httpx.AsyncClient, path: str, label: str) -> None:
    timeline = RetryTimeline()

    async def call() -> httpx.Response:
        return await client.get(path, timeout=2.0)

    outcome = await policy.execute(
        call, operation=label, capture_timeline=timeline, on_log=log_event
    )
    breaker_state = policy.circuit_breaker.state.value if policy.circuit_breaker is not None else "-"
    print_outcome(label, outcome, breaker_state, timeline)


async def demo(base_url: str) -> None:
    policy = build_policy()
    async with httpx.AsyncClient(base_url=base_url) as client:
        print("\n--- retry-after demo ---")
        await run_case(policy, client, "/rate", "retry_after_rate_limit")
        print("\n--- circuit breaker demo ---")
        await run_case(policy, client, "/boom", "breaker_open_attempt_1")
        await run_case(policy, client, "/boom", "breaker_open_attempt_2")
        await run_case(policy, client, "/ok", "circuit_open_reject")
        await asyncio.sleep(0.7)
        await run_case(policy, client, "/ok", "half_open_probe_close")


if __name__ == "__main__":
    server = start_server()
    try:
        asyncio.run(demo(f"http://127.0.0.1:{server.server_port}"))
    finally:
        server.shutdown()
        server.server_close()
