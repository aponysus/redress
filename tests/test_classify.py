# tests/test_classify.py


from redress.classify import default_classifier
from redress.errors import (
    ConcurrencyError,
    ErrorClass,
    PermanentError,
    RateLimitError,
    ServerError,
)


def test_default_classifier_auth_code_401() -> None:
    class AuthStatusError(Exception):
        status = 401

    assert default_classifier(AuthStatusError()) is ErrorClass.AUTH


def test_default_classifier_permission_code_403() -> None:
    class PermissionStatusError(Exception):
        status = 403

    assert default_classifier(PermissionStatusError()) is ErrorClass.PERMISSION


def test_default_classifier_auth_name_heuristic() -> None:
    class UnauthorizedAccessError(Exception):
        pass

    assert default_classifier(UnauthorizedAccessError()) is ErrorClass.AUTH


def test_default_classifier_permission_name_heuristic() -> None:
    class ForbiddenOperationError(Exception):
        pass

    assert default_classifier(ForbiddenOperationError()) is ErrorClass.PERMISSION


def test_default_classifier_400_is_permanent() -> None:
    class BadRequestError(Exception):
        status = 400

    assert default_classifier(BadRequestError()) is ErrorClass.PERMANENT


def test_default_classifier_404_is_permanent() -> None:
    class NotFoundError(Exception):
        status = 404

    assert default_classifier(NotFoundError()) is ErrorClass.PERMANENT


def test_default_classifier_422_is_permanent() -> None:
    class UnprocessableEntityError(Exception):
        status = 422

    assert default_classifier(UnprocessableEntityError()) is ErrorClass.PERMANENT


def test_default_classifier_409_is_concurrency() -> None:
    class ConflictError(Exception):
        status = 409

    assert default_classifier(ConflictError()) is ErrorClass.CONCURRENCY


def test_default_classifier_408_is_transient() -> None:
    class RequestTimeoutError(Exception):
        status = 408

    assert default_classifier(RequestTimeoutError()) is ErrorClass.TRANSIENT


def test_default_classifier_429_is_rate_limit() -> None:
    class TooManyRequestsError(Exception):
        status = 429

    assert default_classifier(TooManyRequestsError()) is ErrorClass.RATE_LIMIT


def test_default_classifier_5xx_is_server_error() -> None:
    class ServerError(Exception):
        status = 502

    assert default_classifier(ServerError()) is ErrorClass.SERVER_ERROR


def test_default_classifier_explicit_redress_types() -> None:
    assert default_classifier(PermanentError()) is ErrorClass.PERMANENT
    assert default_classifier(RateLimitError()) is ErrorClass.RATE_LIMIT
    assert default_classifier(ConcurrencyError()) is ErrorClass.CONCURRENCY
    assert default_classifier(ServerError()) is ErrorClass.SERVER_ERROR


def test_default_classifier_timeout_name_is_transient() -> None:
    class ReadTimeoutError(Exception):
        pass

    assert default_classifier(ReadTimeoutError()) is ErrorClass.TRANSIENT


def test_default_classifier_connection_name_is_transient() -> None:
    class ConnectionResetError(Exception):
        pass

    assert default_classifier(ConnectionResetError()) is ErrorClass.TRANSIENT


def test_default_classifier_unknown_falls_back_to_unknown() -> None:
    class OddballError(Exception):
        pass

    assert default_classifier(OddballError()) is ErrorClass.UNKNOWN
