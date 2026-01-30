"""Optional aiohttp classifier."""

import importlib

from ..classify import default_classifier
from ..errors import ErrorClass
from .http import http_classifier


def aiohttp_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify aiohttp exceptions into ErrorClass.

    This helper is optional and degrades gracefully when aiohttp is unavailable.
    """
    try:
        aiohttp_exc = importlib.import_module("aiohttp.client_exceptions")
    except Exception:
        return default_classifier(exc)

    response_exc = getattr(aiohttp_exc, "ClientResponseError", None)
    if response_exc is not None and isinstance(response_exc, type) and isinstance(exc, response_exc):
        return http_classifier(exc)

    transient_types = tuple(
        t
        for t in (
            getattr(aiohttp_exc, "ClientConnectorError", None),
            getattr(aiohttp_exc, "ClientOSError", None),
            getattr(aiohttp_exc, "ServerDisconnectedError", None),
            getattr(aiohttp_exc, "ClientPayloadError", None),
            getattr(aiohttp_exc, "ClientConnectionError", None),
            getattr(aiohttp_exc, "ServerTimeoutError", None),
        )
        if t is not None
    )
    if transient_types and isinstance(exc, transient_types):
        return ErrorClass.TRANSIENT

    return default_classifier(exc)
