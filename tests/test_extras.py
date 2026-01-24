# tests/test_extras.py

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from redress.classify import Classification, default_classifier
from redress.errors import ErrorClass
from redress.extras import (
    _parse_retry_after,
    http_classifier,
    http_retry_after_classifier,
    sqlstate_classifier,
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
