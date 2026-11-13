"""Antrian ingest berbasis Redis Stream (ADR-D4)."""
from redis.asyncio import Redis

STREAM = "rani:ingest"
GROUP = "rani-workers"


async def enqueue_report(redis: Redis, report_id: str) -> str:
    return await redis.xadd(STREAM, {"report_id": report_id}, maxlen=50_000, approximate=True)


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:  # BUSYGROUP = sudah ada
        if "BUSYGROUP" not in str(exc):
            raise