"""Worker: konsumen Redis Stream → reconciler + requeue sweeper + stale sweep."""
import asyncio
import logging
import signal
import uuid

from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import SessionLocal
from app.ingest.queue import GROUP, STREAM, ensure_group, enqueue_report
from app.ingest.reconciler import mark_stale_assets, process_report
from app.models import SoftwareReport

log = logging.getLogger("rani.worker")
settings = get_settings()
CONSUMER = "worker-1"


async def wait_for_schema(timeout_s: int = 120) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        try:
            async with SessionLocal() as session:
                await session.execute(text("select 1 from rani_inventory.assets limit 1"))
            log.info("schema siap")
            return
        except Exception as exc:
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError("schema tidak siap setelah 120s") from exc
            log.info("menunggu migrasi schema… (%s)", str(exc).splitlines()[0][:120])
            await asyncio.sleep(3)


async def handle_report(redis: Redis, report_id: str) -> None:
    try:
        parsed = uuid.UUID(report_id)
    except ValueError:
        log.error("report_id bukan uuid: %r", report_id)
        return
    async with SessionLocal() as session:
        report = await session.get(SoftwareReport, parsed)
        if report is None:
            # Row belum terlihat (mis. commit tertunda) → biarkan sweeper requeue.
            log.warning("report %s belum ada di DB, dilewati (sweeper akan requeue)", report_id)
            return
        if report.status == "processed":
            return
        try:
            await process_report(session, redis, report)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.exception("gagal proses report %s", report_id)
            async with SessionLocal() as fail_session:
                row = await fail_session.get(SoftwareReport, parsed)
                if row is not None:
                    row.status = "failed"
                    row.error = str(exc)[:2000]
                    await fail_session.commit()


async def consume_loop(redis: Redis) -> None:
    await ensure_group(redis)
    while True:
        try:
            entries = await redis.xreadgroup(GROUP, CONSUMER, {STREAM: ">"},
                                             count=10, block=5000)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("xreadgroup gagal: %s", exc)
            await asyncio.sleep(3)
            continue
        if not entries:
            continue
        for _stream, messages in entries:
            for message_id, fields in messages:
                report_id = fields.get("report_id")
                if report_id:
                    await handle_report(redis, report_id)
                await redis.xack(STREAM, GROUP, message_id)


async def requeue_loop(redis: Redis) -> None:
    """Report 'queued' yang tidak pernah diproses (mis. enqueue gagal) di-enqueue ulang."""
    while True:
        await asyncio.sleep(60)
        try:
            async with SessionLocal() as session:
                rows = (await session.execute(
                    select(SoftwareReport.id).where(
                        SoftwareReport.status == "queued",
                        SoftwareReport.received_at < func.now() - text("interval '2 minutes'"))
                    .limit(200)
                )).scalars().all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("requeue sweep gagal: %s", exc)
            continue
        for report_id in rows:
            try:
                await enqueue_report(redis, str(report_id))
                log.info("requeue report %s", report_id)
            except Exception as exc:
                log.error("requeue %s gagal: %s", report_id, exc)
                break


async def stale_loop(redis: Redis) -> None:
    while True:
        await asyncio.sleep(300)
        try:
            async with SessionLocal() as session:
                count = await mark_stale_assets(session, redis, settings.RANI_OFFLINE_AFTER_S)
            if count:
                log.info("%d asset ditandai offline", count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("stale sweep gagal: %s", exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    await wait_for_schema()
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    consumer = asyncio.create_task(consume_loop(redis))
    requeue = asyncio.create_task(requeue_loop(redis))
    stale = asyncio.create_task(stale_loop(redis))
    log.info("worker siap (stream=%s group=%s consumer=%s)", STREAM, GROUP, CONSUMER)

    await stop.wait()
    for task in (consumer, requeue, stale):
        task.cancel()
    await asyncio.gather(consumer, requeue, stale, return_exceptions=True)
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())