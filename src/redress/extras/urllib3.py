"""Optional urllib3 classifier."""

import importlib

from ..classify import default_classifier
from ..errors import ErrorClass
from .http import _coerce_status, http_classifier


def urllib3_classifier(exc: BaseException) -> ErrorClass:
    """
    Classify urllib3 exceptions into ErrorClass.

    This helper is optional and degrades gracefully when urllib3 is unavailable.
    """
    try:
        urllib3_exc = importlib.import_module("urllib3.exceptions")
    except Exception:
        return default_classifier(exc)

    http_error = getattr(urllib3_exc, "HTTPError", None)
    if http_error is None or not isinstance(http_error, type) or not isinstance(exc, http_error):
        return default_classifier(exc)

    status = _coerce_status(exc)
    if status is not None:
        return http_classifier(exc)

    transient_types = tuple(
        t
        for t in (
            getattr(urllib3_exc, "ConnectTimeoutError", None),
            getattr(urllib3_exc, "ReadTimeoutError", None),
            getattr(urllib3_exc, "NewConnectionError", None),
            getattr(urllib3_exc, "ProtocolError", None),
            getattr(urllib3_exc, "MaxRetryError", None),
        )
        if t is not None
    )
    if transient_types and isinstance(exc, transient_types):
        return ErrorClass.TRANSIENT

    ssl_error = getattr(urllib3_exc, "SSLError", None)
    if ssl_error is not None and isinstance(ssl_error, type) and isinstance(exc, ssl_error):
        return ErrorClass.UNKNOWN

    redirects_error = getattr(urllib3_exc, "TooManyRedirects", None)
    if (
        redirects_error is not None
        and isinstance(redirects_error, type)
        and isinstance(exc, redirects_error)
    ):
        return ErrorClass.PERMANENT

    return default_classifier(exc)
