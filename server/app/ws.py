"""WebSocket hub: event dari worker (Redis pub/sub) → semua client UI."""
import asyncio
import json
import logging

from fastapi import WebSocket
from redis.asyncio import Redis

log = logging.getLogger("rani.ws")
CHANNEL = "rani:events"


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: str) -> None:
        async with self._lock:
            targets = list(self._clients)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:  # client mati / putus
                await self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()


async def publish(redis: Redis, payload: dict) -> None:
    """Dipakai api maupun worker untuk memancarkan event."""
    try:
        await redis.publish(CHANNEL, json.dumps(payload, default=str))
    except Exception as exc:  # pragma: no cover - redis down tidak boleh gagalkan ingest
        log.warning("publish event gagal: %s", exc)


async def listen_forever(redis: Redis) -> None:
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    log.info("ws listener subscribe %s", CHANNEL)
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode()
            await manager.broadcast(data)
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.close()