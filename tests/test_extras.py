# tests/test_extras.py

from redress.errors import ErrorClass
from redress.extras import http_classifier, sqlstate_classifier


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


def test_sqlstate_classifier_unknown_falls_back() -> None:
    class SqlError(Exception):
        def __init__(self) -> None:
            self.sqlstate = "99999"

    assert sqlstate_classifier(SqlError()) is ErrorClass.UNKNOWN
