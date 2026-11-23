import asyncio
import logging
import signal

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import create_async_engine

from common import config

from .worker import run_worker


async def main() -> None:
    engine = create_async_engine(
        config.DATABASE_URL, pool_size=5, pool_pre_ping=True
    )
    redis = aioredis.from_url(config.REDIS_URL, decode_responses=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run_worker(engine, redis, stop)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
