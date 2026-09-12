import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any


class RealtimeManager:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._overflow_count = 0
        self._last_overflow_at: datetime | None = None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._clients):
            if queue.full():
                self._overflow_count += 1
                self._last_overflow_at = datetime.now(UTC)
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                gap_message = {"type": "resync_required", "reason": "client_queue_overflow"}
                try:
                    queue.put_nowait(gap_message)
                except asyncio.QueueFull:
                    pass
            else:
                queue.put_nowait(message)

    def health_snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        recent_overflow = (
            self._last_overflow_at is not None
            and now - self._last_overflow_at <= timedelta(seconds=60)
        )
        return {
            "name": "realtime",
            "status": "degraded" if recent_overflow else "healthy",
            "detail": "client_resync_required" if recent_overflow else "in_process_fanout",
            "checked_at": now.isoformat(),
            "last_success_at": None,
            "metrics": {
                "connected_clients": len(self._clients),
                "queue_overflows": self._overflow_count,
            },
        }


realtime = RealtimeManager()
