"""
AsyncPG example with redress retry.

Requires:
  uv pip install asyncpg
  export ASYNC_PG_DSN="postgres://user:pass@host:5432/dbname"

Run:
  uv run python docs/snippets/asyncpg_retry.py
"""

import asyncio
import os

import asyncpg

from redress import AsyncRetryPolicy
from redress.extras import sqlstate_classifier
from redress.strategies import decorrelated_jitter


def build_policy() -> AsyncRetryPolicy:
    return AsyncRetryPolicy(
        classifier=sqlstate_classifier,
        strategy=decorrelated_jitter(max_s=2.0),
        strategies={
            # 40001/40P01 -> CONCURRENCY gets its own backoff
        },
        max_attempts=5,
        deadline_s=15.0,
        max_unknown_attempts=1,
    )


async def fetch_rows(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT now() AS ts")


async def main() -> None:
    dsn = os.getenv("ASYNC_PG_DSN")
    if not dsn:
        raise SystemExit("Set ASYNC_PG_DSN to a valid Postgres DSN")

    policy = build_policy()

    pool = await asyncpg.create_pool(dsn)
    try:

        async def _call() -> list[asyncpg.Record]:
            return await fetch_rows(pool)

        rows = await policy.call(_call, operation="asyncpg_fetch")
        print(rows)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
