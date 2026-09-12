import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.projections import projector


@pytest.mark.asyncio
async def test_consumer_commits_only_after_every_record_in_fetched_batch_is_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed: list[object] = []

    class FakeConsumer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.polls = 0

        async def start(self) -> None:
            return None

        async def getmany(self, **_kwargs: Any) -> dict[str, list[object]]:
            self.polls += 1
            if self.polls == 1:
                return {"partition": ["event-1", "event-2"]}
            raise asyncio.CancelledError

        async def commit(self) -> None:
            assert processed == ["event-1", "event-2"]

        async def stop(self) -> None:
            return None

    async def process(message: object) -> None:
        processed.append(message)

    monkeypatch.setattr(
        projector,
        "get_settings",
        lambda: SimpleNamespace(
            kafka_topic="livepulse.events.football.v1",
            kafka_bootstrap_servers="unused",
            kafka_consumer_group="test-group",
        ),
    )
    monkeypatch.setattr(projector, "AIOKafkaConsumer", FakeConsumer)
    monkeypatch.setattr(projector, "_process_message", process)

    with pytest.raises(asyncio.CancelledError):
        await projector.run_projector()

    assert processed == ["event-1", "event-2"]
