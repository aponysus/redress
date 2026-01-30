"""Optional boto3/botocore classifier."""

import importlib
from typing import Any

from ..classify import default_classifier
from ..errors import ErrorClass


def boto3_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify boto3/botocore exceptions into ErrorClass.

    This helper is optional and degrades gracefully when botocore is unavailable.
    """
    try:
        botocore_exc = importlib.import_module("botocore.exceptions")
    except Exception:
        return default_classifier(exc)

    endpoint_exc = getattr(botocore_exc, "EndpointConnectionError", None)
    if endpoint_exc is not None and isinstance(endpoint_exc, type) and isinstance(exc, endpoint_exc):
        return ErrorClass.TRANSIENT

    connection_closed_exc = getattr(botocore_exc, "ConnectionClosedError", None)
    if (
        connection_closed_exc is not None
        and isinstance(connection_closed_exc, type)
        and isinstance(exc, connection_closed_exc)
    ):
        return ErrorClass.TRANSIENT

    read_timeout_exc = getattr(botocore_exc, "ReadTimeoutError", None)
    if read_timeout_exc is not None and isinstance(read_timeout_exc, type) and isinstance(exc, read_timeout_exc):
        return ErrorClass.TRANSIENT

    connect_timeout_exc = getattr(botocore_exc, "ConnectTimeoutError", None)
    if connect_timeout_exc is not None and isinstance(connect_timeout_exc, type) and isinstance(exc, connect_timeout_exc):
        return ErrorClass.TRANSIENT

    client_error = getattr(botocore_exc, "ClientError", None)
    if client_error is not None and isinstance(client_error, type) and isinstance(exc, client_error):
        return _classify_client_error(exc)

    return default_classifier(exc)


def _classify_client_error(exc: BaseException) -> ErrorClass:
    response: dict[str, Any] = getattr(exc, "response", {}) or {}
    error_info = response.get("Error", {}) if isinstance(response, dict) else {}
    metadata = response.get("ResponseMetadata", {}) if isinstance(response, dict) else {}

    code = error_info.get("Code") if isinstance(error_info, dict) else None
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None

    throttling_codes = {
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
        "RequestLimitExceeded",
        "SlowDown",
    }
    if isinstance(code, str):
        if code in throttling_codes:
            return ErrorClass.RATE_LIMIT
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            return ErrorClass.PERMISSION
        if code in {"UnrecognizedClientException", "InvalidClientTokenId", "ExpiredToken"}:
            return ErrorClass.AUTH

    if isinstance(status, int):
        if status == 429:
            return ErrorClass.RATE_LIMIT
        if status in {401, 403}:
            return ErrorClass.AUTH if status == 401 else ErrorClass.PERMISSION
        if 500 <= status < 600:
            return ErrorClass.SERVER_ERROR
        if 400 <= status < 500:
            return ErrorClass.PERMANENT

    return ErrorClass.UNKNOWN
