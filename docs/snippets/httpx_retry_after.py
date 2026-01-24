"""
HTTP retry example that honors Retry-After and uses result-based retries.

Run with:
    uv pip install httpx
    uv run python docs/snippets/httpx_retry_after.py
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any

import httpx

from redress import Classification, ErrorClass, Policy, Retry
from redress.extras import http_retry_after_classifier
from redress.strategies import decorrelated_jitter, retry_after_or


def log_event(event: str, fields: dict[str, Any]) -> None:
    print(f"[log] event={event} fields={fields}")


class DemoHandler(BaseHTTPRequestHandler):
    rate_count = 0
    flaky_count = 0

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler hook name
        path = self.path.split("?", 1)[0]
        if path == "/rate":
            DemoHandler.rate_count += 1
            if DemoHandler.rate_count < 3:
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.end_headers()
                return
        if path == "/flaky":
            DemoHandler.flaky_count += 1
            if DemoHandler.flaky_count < 3:
                self.send_response(503)
                self.end_headers()
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


def build_policy() -> Policy:
    return Policy(
        retry=Retry(
            classifier=http_retry_after_classifier,
            result_classifier=classify_result,
            strategy=retry_after_or(decorrelated_jitter(max_s=3.0)),
            deadline_s=8.0,
            max_attempts=5,
        )
    )


def demo(base_url: str) -> None:
    policy = build_policy()
    with httpx.Client(base_url=base_url) as client:
        with policy.context(on_log=log_event, operation="http_demo") as call:
            for path in ("/rate", "/flaky", "/ok"):
                response = call(client.get, path, timeout=2.0)
                print(f"{path} -> {response.status_code} {response.text!r}")


if __name__ == "__main__":
    server = start_server()
    try:
        demo(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
