# tests/test_extras.py

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from redress.classify import Classification, default_classifier
from redress.errors import ErrorClass
from redress.extras import (
    _parse_retry_after,
    aiohttp_classifier,
    boto3_classifier,
    grpc_classifier,
    http_classifier,
    http_retry_after_classifier,
    redis_classifier,
    sqlstate_classifier,
    urllib3_classifier,
)


def test_http_classifier_mappings() -> None:
    class HttpError(Exception):
        def __init__(self, status: int) -> None:
            self.status = status

    assert http_classifier(HttpError(401)) is ErrorClass.AUTH
    assert http_classifier(HttpError(403)) is ErrorClass.PERMISSION
    assert http_classifier(HttpError(409)) is ErrorClass.CONCURRENCY
    assert http_classifier(HttpError(429)) is ErrorClass.RATE_LIMIT
    assert http_classifier(HttpError(500)) is ErrorClass.SERVER_ERROR
    assert http_classifier(HttpError(408)) is ErrorClass.TRANSIENT
    assert http_classifier(HttpError(404)) is ErrorClass.PERMANENT


def test_sqlstate_classifier_mappings() -> None:
    class SqlError(Exception):
        def __init__(self, sqlstate: str) -> None:
            self.sqlstate = sqlstate

    assert sqlstate_classifier(SqlError("40001")) is ErrorClass.CONCURRENCY
    assert sqlstate_classifier(SqlError("40P01")) is ErrorClass.CONCURRENCY
    assert sqlstate_classifier(SqlError("HYT00")) is ErrorClass.TRANSIENT
    assert sqlstate_classifier(SqlError("08S01")) is ErrorClass.TRANSIENT
    assert sqlstate_classifier(SqlError("28000")) is ErrorClass.AUTH
    assert sqlstate_classifier(SqlError("42000")) is ErrorClass.PERMANENT


def test_http_classifier_from_args() -> None:
    class HttpError(Exception):
        pass

    err = HttpError(0)
    err.args = (429,)  # type: ignore[assignment]
    assert http_classifier(err) is ErrorClass.RATE_LIMIT


def test_http_classifier_ignores_non_http_int_args() -> None:
    class MiscError(Exception):
        pass

    err = MiscError(13)
    err.args = (13,)  # type: ignore[assignment]
    assert http_classifier(err) is default_classifier(err)


def test_http_classifier_from_status_code_attr() -> None:
    class HttpError(Exception):
        def __init__(self) -> None:
            self.status_code = 429

    assert http_classifier(HttpError()) is ErrorClass.RATE_LIMIT


def test_http_classifier_from_code_attr() -> None:
    class HttpError(Exception):
        def __init__(self) -> None:
            self.code = 503

    assert http_classifier(HttpError()) is ErrorClass.SERVER_ERROR


def test_sqlstate_classifier_from_string_args() -> None:
    class SqlError(Exception):
        pass

    err = SqlError("[HYT00]")
    err.args = ("[HYT00] timeout",)  # type: ignore[assignment]
    assert sqlstate_classifier(err) is ErrorClass.TRANSIENT


def test_http_classifier_unknown_falls_back() -> None:
    class HttpError(Exception):
        def __init__(self) -> None:
            self.status_code = 777

    assert http_classifier(HttpError()) is ErrorClass.UNKNOWN


def test_urllib3_classifier_mappings() -> None:
    pytest.importorskip("urllib3")
    from urllib3 import exceptions as urllib3_exc

    if getattr(urllib3_exc, "ReadTimeoutError", None) is not None:

        class FakeReadTimeoutError(urllib3_exc.ReadTimeoutError):
            def __init__(self) -> None:
                Exception.__init__(self, "timeout")

        assert urllib3_classifier(FakeReadTimeoutError()) is ErrorClass.TRANSIENT

    redirects_exc = getattr(urllib3_exc, "TooManyRedirects", None)
    if redirects_exc is not None:

        class FakeTooManyRedirects(redirects_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "redirects")

        assert urllib3_classifier(FakeTooManyRedirects()) is ErrorClass.PERMANENT

    ssl_exc = getattr(urllib3_exc, "SSLError", None)
    if ssl_exc is not None:

        class FakeSSLError(ssl_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "ssl")

        assert urllib3_classifier(FakeSSLError()) is ErrorClass.UNKNOWN

    class FakeHttpStatus(urllib3_exc.HTTPError):
        def __init__(self) -> None:
            Exception.__init__(self, "status")
            self.status = 429

    assert urllib3_classifier(FakeHttpStatus()) is ErrorClass.RATE_LIMIT


def test_redis_classifier_mappings() -> None:
    pytest.importorskip("redis")
    from redis import exceptions as redis_exc

    timeout_exc = getattr(redis_exc, "TimeoutError", None)
    if timeout_exc is not None:

        class FakeTimeout(timeout_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "timeout")

        assert redis_classifier(FakeTimeout()) is ErrorClass.TRANSIENT

    connection_exc = getattr(redis_exc, "ConnectionError", None)
    if connection_exc is not None:

        class FakeConnection(connection_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "conn")

        assert redis_classifier(FakeConnection()) is ErrorClass.TRANSIENT

    busy_exc = getattr(redis_exc, "BusyLoadingError", None)
    if busy_exc is not None:

        class FakeBusy(busy_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "busy")

        assert redis_classifier(FakeBusy()) is ErrorClass.TRANSIENT

    readonly_exc = getattr(redis_exc, "ReadOnlyError", None)
    if readonly_exc is not None:

        class FakeReadonly(readonly_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "readonly")

        assert redis_classifier(FakeReadonly()) is ErrorClass.CONCURRENCY

    auth_exc = getattr(redis_exc, "AuthenticationError", None)
    if auth_exc is not None:

        class FakeAuth(auth_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "auth")

        assert redis_classifier(FakeAuth()) is ErrorClass.AUTH

    perm_exc = getattr(redis_exc, "AuthorizationError", None)
    if perm_exc is not None:

        class FakePerm(perm_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "perm")

        assert redis_classifier(FakePerm()) is ErrorClass.PERMISSION


def test_aiohttp_classifier_mappings() -> None:
    pytest.importorskip("aiohttp")
    from aiohttp import client_exceptions as aiohttp_exc

    conn_exc = getattr(aiohttp_exc, "ClientConnectionError", None)
    if conn_exc is not None:

        class FakeConnection(conn_exc):
            def __init__(self) -> None:
                Exception.__init__(self, "conn")

        assert aiohttp_classifier(FakeConnection()) is ErrorClass.TRANSIENT

    resp_exc = getattr(aiohttp_exc, "ClientResponseError", None)
    if resp_exc is not None:
        fake_resp = None
        try:

            class FakeResponse(resp_exc):
                def __init__(self) -> None:
                    Exception.__init__(self, "resp")
                    self.status = 429

            fake_resp = FakeResponse()
        except Exception:
            fake_resp = None

        if fake_resp is not None:
            assert aiohttp_classifier(fake_resp) is ErrorClass.RATE_LIMIT


def test_grpc_classifier_mappings() -> None:
    pytest.importorskip("grpc")
    import grpc

    class FakeRpcError(grpc.RpcError):
        def __init__(self, status: grpc.StatusCode) -> None:
            super().__init__()
            self._status = status

        def code(self) -> grpc.StatusCode:
            return self._status

    assert (
        grpc_classifier(FakeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED)) is ErrorClass.RATE_LIMIT
    )
    assert grpc_classifier(FakeRpcError(grpc.StatusCode.UNAVAILABLE)) is ErrorClass.TRANSIENT
    assert grpc_classifier(FakeRpcError(grpc.StatusCode.UNAUTHENTICATED)) is ErrorClass.AUTH
    assert grpc_classifier(FakeRpcError(grpc.StatusCode.PERMISSION_DENIED)) is ErrorClass.PERMISSION
    assert grpc_classifier(FakeRpcError(grpc.StatusCode.INTERNAL)) is ErrorClass.SERVER_ERROR


def test_boto3_classifier_mappings() -> None:
    pytest.importorskip("botocore")
    from botocore.exceptions import ClientError, EndpointConnectionError

    endpoint_error = EndpointConnectionError(endpoint_url="https://example.com")
    assert boto3_classifier(endpoint_error) is ErrorClass.TRANSIENT

    throttling_error = ClientError(
        {
            "Error": {"Code": "Throttling", "Message": "slow down"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        },
        "ListTables",
    )
    assert boto3_classifier(throttling_error) is ErrorClass.RATE_LIMIT

    perm_error = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "nope"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "ListTables",
    )
    assert boto3_classifier(perm_error) is ErrorClass.PERMISSION

    auth_error = ClientError(
        {
            "Error": {"Code": "InvalidClientTokenId", "Message": "bad token"},
            "ResponseMetadata": {"HTTPStatusCode": 401},
        },
        "ListTables",
    )
    assert boto3_classifier(auth_error) is ErrorClass.AUTH

    server_error = ClientError(
        {
            "Error": {"Code": "InternalError", "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        },
        "ListTables",
    )
    assert boto3_classifier(server_error) is ErrorClass.SERVER_ERROR

    permanent_error = ClientError(
        {
            "Error": {"Code": "ResourceNotFoundException", "Message": "missing"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "ListTables",
    )
    assert boto3_classifier(permanent_error) is ErrorClass.PERMANENT


def test_http_retry_after_classifier_seconds() -> None:
    class HttpError(Exception):
        def __init__(self, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers

    result = http_retry_after_classifier(HttpError(429, {"Retry-After": "120"}))
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s == 120.0


def test_http_retry_after_classifier_http_date() -> None:
    class HttpError(Exception):
        def __init__(self, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers

    retry_at = datetime.now(UTC) + timedelta(seconds=5)
    header = format_datetime(retry_at)
    result = http_retry_after_classifier(HttpError(429, {"Retry-After": header}))
    assert isinstance(result, Classification)
    assert result.klass is ErrorClass.RATE_LIMIT
    assert result.retry_after_s is not None
    assert 0.0 <= result.retry_after_s <= 6.0


def test_http_retry_after_classifier_direct_retry_after() -> None:
    class HttpError(Exception):
        def __init__(self, status: int, retry_after: object) -> None:
            self.status = status
            self.retry_after = retry_after

    result = http_retry_after_classifier(HttpError(429, 7))
    assert isinstance(result, Classification)
    assert result.retry_after_s == 7.0

    result = http_retry_after_classifier(HttpError(429, "5"))
    assert isinstance(result, Classification)
    assert result.retry_after_s == 5.0


def test_http_retry_after_classifier_ignores_invalid_retry_after() -> None:
    class HttpError(Exception):
        def __init__(self, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers

    result = http_retry_after_classifier(HttpError(429, {"Retry-After": "junk"}))
    assert result is ErrorClass.RATE_LIMIT


def test_http_retry_after_classifier_non_rate_limit() -> None:
    class HttpError(Exception):
        def __init__(self, status: int, headers: dict[str, str]) -> None:
            self.status = status
            self.headers = headers

    result = http_retry_after_classifier(HttpError(503, {"Retry-After": "5"}))
    assert result is ErrorClass.SERVER_ERROR


def test_http_retry_after_classifier_header_shapes() -> None:
    class HeadersObj:
        def __init__(self, data: list[tuple[str, str]]) -> None:
            self._data = data

        def get(self, key: str) -> None:
            return None

        def items(self) -> list[tuple[str, str]]:
            return self._data

    class HttpError(Exception):
        def __init__(self, status: int, headers: object) -> None:
            self.status = status
            self.headers = headers

    result = http_retry_after_classifier(HttpError(429, {"retry-after": "3"}))
    assert isinstance(result, Classification)
    assert result.retry_after_s == 3.0

    result = http_retry_after_classifier(HttpError(429, HeadersObj([("Retry-After", "4")])))
    assert isinstance(result, Classification)
    assert result.retry_after_s == 4.0

    result = http_retry_after_classifier(HttpError(429, [("Retry-After", "6")]))
    assert isinstance(result, Classification)
    assert result.retry_after_s == 6.0


def test_parse_retry_after_naive_date() -> None:
    parsed = _parse_retry_after("Wed, 21 Oct 2015 07:28:00")
    assert parsed is not None
    assert parsed >= 0.0


def test_sqlstate_classifier_unknown_falls_back() -> None:
    class SqlError(Exception):
        def __init__(self) -> None:
            self.sqlstate = "99999"

    assert sqlstate_classifier(SqlError()) is ErrorClass.UNKNOWN
