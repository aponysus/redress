"""Optional helper classifiers for common domains.

Dependency-free by default. Some classifiers attempt optional imports and
fall back to default_classifier when dependencies are missing.
"""

from .aiohttp import aiohttp_classifier
from .boto3 import boto3_classifier
from .grpc import grpc_classifier
from .http import _parse_retry_after, http_classifier, http_retry_after_classifier
from .pyodbc import pyodbc_classifier
from .redis import redis_classifier
from .sqlstate import sqlstate_classifier
from .urllib3 import urllib3_classifier

__all__ = [
    "_parse_retry_after",
    "aiohttp_classifier",
    "boto3_classifier",
    "grpc_classifier",
    "http_classifier",
    "http_retry_after_classifier",
    "pyodbc_classifier",
    "redis_classifier",
    "sqlstate_classifier",
    "urllib3_classifier",
]
