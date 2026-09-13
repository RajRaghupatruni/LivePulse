import os

import pytest_asyncio

from app.storage.database import engine


@pytest_asyncio.fixture(scope="module", autouse=True, loop_scope="module")
async def dispose_shared_engine_between_integration_modules():
    """Avoid carrying pooled asyncpg connections across module-scoped event loops."""
    yield
    if os.getenv("LIVEPULSE_INTEGRATION") == "1":
        await engine.dispose()
