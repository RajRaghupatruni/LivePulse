"""Give opt-in integration tests broker ownership separate from the live API."""

import asyncio
import os
import warnings
from uuid import uuid4

import pytest_asyncio

_integration_topic: str | None = None
if os.getenv("LIVEPULSE_INTEGRATION") == "1":
    _integration_topic = f"livepulse.events.integration.{uuid4().hex}"
    # This conftest is loaded before integration test modules import app settings.
    # The override is process-local and never changes the developer's .env or API process.
    os.environ["KAFKA_TOPIC"] = _integration_topic


@pytest_asyncio.fixture(scope="module", autouse=True, loop_scope="module")
async def dispose_database_pool_between_module_loops():
    """Keep asyncpg connections from crossing pytest's module-scoped event loops."""
    if os.getenv("LIVEPULSE_INTEGRATION") != "1":
        yield
        return

    from app.storage.database import engine

    yield
    await engine.dispose()


async def _delete_integration_topic(topic: str) -> None:
    from aiokafka.admin import AIOKafkaAdminClient

    from app.core.config import get_settings

    admin = AIOKafkaAdminClient(
        bootstrap_servers=get_settings().kafka_bootstrap_servers
    )
    started = False
    try:
        await admin.start()
        started = True
        if topic in await admin.list_topics():
            await admin.delete_topics([topic], timeout_ms=15_000)
    finally:
        if started:
            await admin.close()


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    del session, exitstatus
    if _integration_topic is None:
        return
    try:
        asyncio.run(_delete_integration_topic(_integration_topic))
    except Exception as exc:
        warnings.warn(
            f"Could not remove the temporary integration Kafka topic ({type(exc).__name__}).",
            RuntimeWarning,
            stacklevel=1,
        )
