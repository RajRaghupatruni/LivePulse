import asyncio
from typing import Any


class RealtimeManager:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._clients):
            if queue.full():
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


realtime = RealtimeManager()
