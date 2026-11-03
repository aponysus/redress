"""Request replay contracts exercised through real HTTPX transports."""

import asyncio
import copy
import io
from collections.abc import AsyncIterator, Callable
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any

import pytest

from redress import AsyncPolicy, AsyncRetry, Policy, Retry, default_classifier
from redress.contrib.httpx import (
    AsyncRetryingHttpxClient,
    RetryingHttpxClient,
    arequest_with_retry,
    default_result_classifier,
    request_with_retry,
)

httpx = pytest.importorskip("httpx")


@pytest.fixture(params=["sync", "async", "sync_wrapper", "async_wrapper"])
def mode(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def send(mode: str) -> Callable[..., Any]:
    def run(handler: Callable[..., Any], **kwargs: Any) -> Any:
        options = dict(
            classifier=default_classifier,
            result_classifier=default_result_classifier,
            strategy=lambda _ctx: 0.0,
            max_attempts=2,
        )
        url = "https://example.invalid/item"
        if mode.startswith("sync"):
            policy = Policy(retry=Retry(**options))
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                if mode == "sync_wrapper":
                    return RetryingHttpxClient(client, policy).put(url, **kwargs)
                return request_with_retry(client, policy, "PUT", url, **kwargs)

        async def arun() -> Any:
            policy = AsyncPolicy(retry=AsyncRetry(**options))
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                if mode == "async_wrapper":
                    return await AsyncRetryingHttpxClient(client, policy).put(url, **kwargs)
                return await arequest_with_retry(client, policy, "PUT", url, **kwargs)

        return asyncio.run(arun())

    return run


@pytest.mark.parametrize("failure", ["status", "exception"])
@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, b""),
        ({"content": b"payload\x00"}, b"payload\x00"),
        ({"content": "café"}, "café".encode()),
        ({"content": b""}, b""),
        ({"data": b"payload"}, b"payload"),
        ({"data": "payload"}, b"payload"),
        ({"data": {"tag": ["a", "b"], "enabled": True}}, b"tag=a&tag=b&enabled=true"),
        (
            {"json": {"items": [1, {"name": "café"}], "ok": True}},
            '{"items":[1,{"name":"café"}],"ok":true}'.encode(),
        ),
    ],
)
def test_buffered_bodies_survive_retries(
    send: Callable[..., Any], kwargs: dict[str, Any], expected: bytes, failure: str
) -> None:
    bodies = []

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        if len(bodies) == 1:
            if failure == "exception":
                raise TimeoutError("response lost after upload")
            return httpx.Response(503)
        return httpx.Response(200)

    response = send(handler, **kwargs)
    assert response.status_code == 200
    assert bodies == [expected, expected]


@pytest.mark.parametrize("body_kind", ["json", "data", "files"])
def test_mutating_original_containers_does_not_change_retries(
    send: Callable[..., Any], body_kind: str
) -> None:
    values: dict[str, Any] = {
        "json": {"items": [{"name": "original"}]},
        "data": {"tag": ["original"]},
        "files": [("upload", ("data.txt", b"original", "text/plain", {"X-Part": "original"}))],
    }
    original = values[body_kind]
    kwargs = {body_kind: original}
    if body_kind == "files":
        kwargs["headers"] = {"Content-Type": "multipart/form-data; boundary=test-boundary"}
    bodies = []

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        if body_kind == "json":
            original["items"][0]["name"] = "changed"
        elif body_kind == "data":
            original["tag"][0] = "changed"
        else:
            original[0][1][3]["X-Part"] = "changed"
            original.append(("extra", b"changed"))
        return httpx.Response(503 if len(bodies) == 1 else 200)

    assert send(handler, **kwargs).status_code == 200
    assert len(bodies) == 2
    assert b"original" in bodies[0]
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("as_mapping", [False, True])
def test_buffered_multipart_preserves_parts_and_caller_headers(
    send: Callable[..., Any], as_mapping: bool
) -> None:
    files = [
        ("upload", ("data.bin", b"payload\x00", "application/custom", {"X-Part": "value"})),
        ("text", (None, "café")),
        ("bare", b"buffered"),
    ]
    original = copy.deepcopy(files)
    attempts = []

    def handler(request: Any) -> Any:
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: "
            + request.headers["Content-Type"].encode()
            + b"\r\n\r\n"
            + request.read()
        )
        parts = [
            (
                part.get_param("name", header="Content-Disposition"),
                part.get_filename(),
                part.get_content_type(),
                part.get("X-Part"),
                part.get_payload(decode=True),
            )
            for part in message.iter_parts()
        ]
        attempts.append(parts)
        return httpx.Response(503 if len(attempts) == 1 else 200)

    response = send(
        handler, data={"tag": ["one", "two"]}, files=dict(files) if as_mapping else files
    )
    assert response.status_code == 200
    expected = [
        ("tag", None, "text/plain", None, b"one"),
        ("tag", None, "text/plain", None, b"two"),
        ("upload", "data.bin", "application/custom", "value", b"payload\x00"),
        ("text", None, "text/plain", None, "café".encode()),
        ("bare", "upload", "application/octet-stream", None, b"buffered"),
    ]
    assert attempts == [expected, expected]
    assert files == original


@pytest.mark.parametrize("as_proxy", [False, True])
@pytest.mark.parametrize("body_kind", ["form", "multipart_form", "uploads"])
def test_duplicate_mapping_keys_rejected_before_policy_or_send(
    send: Callable[..., Any], as_proxy: bool, body_kind: str
) -> None:
    multidict = pytest.importorskip("multidict")
    entries = (
        [("upload", ("one.txt", b"one")), ("upload", ("two.txt", b"two"))]
        if body_kind == "uploads"
        else [("tag", "one"), ("tag", "two")]
    )
    original = multidict.MultiDict(entries)
    body = multidict.MultiDictProxy(original) if as_proxy else original
    kwargs = {"files" if body_kind == "uploads" else "data": body}
    if body_kind == "multipart_form":
        kwargs["files"] = {"upload": ("file.txt", b"payload")}
    attempts = []
    bodies = []

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        return httpx.Response(200)

    with pytest.raises(TypeError, match="duplicate mapping keys"):
        send(handler, call_kwargs={"on_attempt_start": attempts.append}, **kwargs)

    assert attempts == []
    assert bodies == []
    assert list(original.items()) == entries


@pytest.mark.parametrize("as_proxy", [False, True])
def test_unique_mapping_keys_still_replay(send: Callable[..., Any], as_proxy: bool) -> None:
    multidict = pytest.importorskip("multidict")
    data = multidict.MultiDict([("tag", "one"), ("other", "two")])
    bodies = []

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        data["tag"] = "changed"
        return httpx.Response(503 if len(bodies) == 1 else 200)

    response = send(handler, data=multidict.MultiDictProxy(data) if as_proxy else data)
    assert response.status_code == 200
    assert bodies == [b"tag=one&other=two", b"tag=one&other=two"]


def test_repeated_multipart_fields_and_uploads_replay(send: Callable[..., Any]) -> None:
    attempts = []

    def handler(request: Any) -> Any:
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: "
            + request.headers["Content-Type"].encode()
            + b"\r\n\r\n"
            + request.read()
        )
        attempts.append(
            [
                (
                    part.get_param("name", header="Content-Disposition"),
                    part.get_filename(),
                    part.get_payload(decode=True),
                )
                for part in message.iter_parts()
            ]
        )
        return httpx.Response(503 if len(attempts) == 1 else 200)

    response = send(
        handler,
        data={"tag": ["one", "two"]},
        files=[("upload", ("one.txt", b"one")), ("upload", ("two.txt", b"two"))],
    )
    expected = [
        ("tag", None, b"one"),
        ("tag", None, b"two"),
        ("upload", "one.txt", b"one"),
        ("upload", "two.txt", b"two"),
    ]
    assert response.status_code == 200
    assert attempts == [expected, expected]


@pytest.mark.parametrize("argument", ["content", "data", "files"])
def test_iterators_rejected_before_consumption_or_send(
    send: Callable[..., Any], argument: str
) -> None:
    chunks = iter([b"payload"])
    bodies = []

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        return httpx.Response(503 if len(bodies) == 1 else 200)

    body = chunks if argument != "files" else iter([("upload", b"payload")])
    with pytest.raises(TypeError, match="replayable.*" + argument):
        send(handler, **{argument: body})
    assert bodies == []
    assert next(body) == (b"payload" if argument != "files" else ("upload", b"payload"))


def test_async_stream_rejected_without_consumption(send: Callable[..., Any]) -> None:
    consumed = []

    async def content() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"payload"

    def handler(request: Any) -> Any:
        pytest.fail("unsupported body must not reach the transport")

    with pytest.raises(TypeError, match="replayable.*content"):
        send(handler, content=content())
    assert consumed == []


def test_unseekable_multipart_file_is_not_read(send: Callable[..., Any]) -> None:
    class UnseekableFile:
        def read(self, size: int = -1) -> bytes:
            pytest.fail("validation must not read an unbounded stream")

    def handler(request: Any) -> Any:
        pytest.fail("unsupported upload must not reach the transport")

    with pytest.raises(TypeError, match="replayable.*files"):
        send(handler, files=[("upload", ("data.bin", UnseekableFile()))])


def test_cyclic_json_rejected_before_sending(send: Callable[..., Any]) -> None:
    body: list[Any] = []
    body.append(body)

    def handler(request: Any) -> Any:
        pytest.fail("cyclic JSON must not reach the transport")

    with pytest.raises(TypeError, match="replayable.*json"):
        send(handler, json=body)


@pytest.mark.parametrize("argument", ["content", "data", "file", "file_tuple"])
@pytest.mark.parametrize("offset", [0, 7])
def test_file_bodies_rejected_without_reading_rewinding_or_closing(
    send: Callable[..., Any], argument: str, offset: int
) -> None:
    with io.BytesIO(b"prefix:payload") as source:
        source.seek(offset)
        kwargs = {argument: source}
        if argument.startswith("file"):
            kwargs = {"files": {"upload": source if argument == "file" else ("data.bin", source)}}

        def handler(request: Any) -> Any:
            pytest.fail("file body must not reach the transport")

        with pytest.raises(TypeError, match="replayable"):
            send(handler, **kwargs)
        assert source.tell() == offset
        assert not source.closed


def test_skip_if_sends_stream_once(send: Callable[..., Any], mode: str) -> None:
    bodies = []

    async def content() -> AsyncIterator[bytes]:
        yield b"payload"

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        return httpx.Response(503)

    body = content() if mode.startswith("async") else iter([b"payload"])
    response = send(handler, content=body, skip_if=lambda _method, _url: True)
    assert response.status_code == 503
    assert bodies == [b"payload"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_unsupported_body_rejected_before_policy_execution(asynchronous: bool) -> None:
    class UnusedPolicy:
        def call(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("validation must happen before entering the policy")

    class UnusedClient:
        def request(self, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("validation must happen before calling the client")

    with pytest.raises(TypeError, match="replayable.*content"):
        if asynchronous:
            asyncio.run(
                arequest_with_retry(
                    UnusedClient(), UnusedPolicy(), "PUT", "/item", content=iter([b"payload"])
                )
            )
        else:
            request_with_retry(
                UnusedClient(), UnusedPolicy(), "PUT", "/item", content=iter([b"payload"])
            )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_direct_policy_call_can_recreate_a_stream_each_attempt(
    tmp_path: Path, asynchronous: bool
) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"prefix:payload")
    bodies = []
    sources = []
    options = dict(
        classifier=default_classifier,
        result_classifier=default_result_classifier,
        strategy=lambda _ctx: 0.0,
        max_attempts=2,
    )

    def handler(request: Any) -> Any:
        bodies.append(request.read())
        return httpx.Response(503 if len(bodies) == 1 else 200)

    if asynchronous:

        async def run() -> Any:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

                async def upload() -> Any:
                    async def chunks() -> AsyncIterator[bytes]:
                        with path.open("rb") as source:
                            sources.append(source)
                            source.seek(7)
                            yield source.read()

                    return await client.put("https://example.invalid/item", content=chunks())

                return await AsyncPolicy(retry=AsyncRetry(**options)).call(upload)

        response = asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:

            def upload() -> Any:
                with path.open("rb") as source:
                    sources.append(source)
                    source.seek(7)
                    return client.put("https://example.invalid/item", content=source)

            response = Policy(retry=Retry(**options)).call(upload)

    assert response.status_code == 200
    assert bodies == [b"payload", b"payload"]
    assert len(sources) == 2
    assert all(source.closed for source in sources)
