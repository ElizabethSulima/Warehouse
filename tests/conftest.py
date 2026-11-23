import asyncio
import os

import pytest
import pytest_asyncio
import sqlalchemy as sa
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from common import config
from common.migrate import run_migrations
from inventory_api.app import create_app

_default_test_db = (
    make_url(config.DATABASE_URL)
    .set(database="warehouse_test")
    .render_as_string(hide_password=False)
)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or _default_test_db
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL") or "redis://localhost:6379/1"


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    asyncio.run(run_migrations(TEST_DATABASE_URL))


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        await conn.execute(
            sa.text("TRUNCATE stock_events, stock_agg RESTART IDENTITY")
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    app = create_app(TEST_DATABASE_URL, TEST_REDIS_URL)
    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()
