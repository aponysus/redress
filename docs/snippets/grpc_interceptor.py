"""
gRPC unary-unary client interceptor integration.

Run:
    uv pip install "redress[grpc]"

Then plug the channel into your generated gRPC stubs.
"""

from redress import AsyncRetryPolicy, RetryPolicy
from redress.contrib.grpc import (
    aio_unary_unary_client_interceptor,
    rpc_method_name,
    unary_unary_client_interceptor,
)
from redress.extras import grpc_classifier
from redress.strategies import decorrelated_jitter


def build_sync_channel(target: str):
    import grpc

    policy = RetryPolicy(
        classifier=grpc_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        max_attempts=4,
        deadline_s=5.0,
    )
    interceptor = unary_unary_client_interceptor(
        policy,
        # Example guard: avoid retrying known write-style method names.
        skip_if=lambda details, _request: (rpc_method_name(details) or "").startswith("Create"),
    )
    return grpc.intercept_channel(grpc.insecure_channel(target), interceptor)


def build_async_channel(target: str):
    import grpc.aio

    policy = AsyncRetryPolicy(
        classifier=grpc_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        max_attempts=4,
        deadline_s=5.0,
    )
    interceptor = aio_unary_unary_client_interceptor(
        policy,
        skip_if=lambda details, _request: (rpc_method_name(details) or "").startswith("Create"),
    )
    return grpc.aio.insecure_channel(target, interceptors=[interceptor])


if __name__ == "__main__":
    # Replace with your service endpoint and generated stubs.
    sync_channel = build_sync_channel("127.0.0.1:50051")
    async_channel = build_async_channel("127.0.0.1:50051")
    print(sync_channel, async_channel)
