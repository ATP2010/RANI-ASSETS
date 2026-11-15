"""Ingest push: identifikasi agent, verifikasi, skema, idempotensi → Redis Stream.

Dua mode diterima (lihat agent/raniPush.py):

1. Langsung / tanpa token (default)
   `raniPush <ip:port>` mengirim payload tanpa enroll. Agent dikenali dari
   `identity.machine_id` (fallback: hostname) di dalam payload; server membuat
   baris agent otomatis pada push pertama. Header yang wajib:
     X-Rani-Digest     sha256:<hex body>   (integritas body)
     X-Rani-Timestamp  ISO-8601 UTC        (anti-replay jendela skew)
     X-Rani-Nonce      unik per push       (anti-replay)
   Tidak ada signature: siapa pun yang bisa menjangkau port ini bisa mengirim
   inventaris. Itu pilihan owner untuk LAN internal — matikan dengan
   RANI_TOKENLESS_PUSH=0 bila perlu HMAC wajib.

2. Enroll + HMAC (legacy, tetap didukung)
     X-Rani-Agent-Id + X-Rani-Signature = HMAC_SHA256(agent_secret, ts + nonce + body)
   Signature opsional pada agent yang sudah punya secret; bila dikirim, harus valid.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jsonschema import Draft202012Validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import get_settings
from app.crypto import decrypt_secret
from app.db import get_session
from app.ingest.queue import enqueue_report
from app.models import Agent, SoftwareReport
from app.security import constant_eq, hmac_hex, sha256_hex

log = logging.getLogger("rani.ingest")
router = APIRouter(tags=["ingest"])
settings = get_settings()

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "agent_payload_v1.json"
with _SCHEMA_PATH.open(encoding="utf-8") as fh:
    _SCHEMAS = {1: Draft202012Validator(json.load(fh))}


def _parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Rani-Timestamp tidak valid") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _resolve_agent(session: AsyncSession, request: Request, payload: dict,
                         headers: dict) -> tuple[Agent, str]:
    """Kembalikan (agent, mode). Mode `signed` bila agent dikenali dari header id.

    Mode `direct`: agent dicari lewat machine_id, lalu hostname untuk agent yang
    belum punya machine_id/secret (jangan menyerobot agent hasil enroll). Push
    pertama membuat baris agent baru supaya report punya FK yang sah.
    """
    now = datetime.now(timezone.utc)
    agent_id = headers.get("agent_id")

    if agent_id:
        agent = (await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )).scalar_one_or_none()
        if agent is not None and agent.revoked_at is not None:
            identity = payload.get("identity") or {}
            log.warning(
                "push ditolak 401: agent %s sudah direvoke — machine_id=%s hostname=%s",
                agent_id, identity.get("machine_id"), identity.get("hostname"))
            raise HTTPException(status_code=401, detail="agent tidak dikenal/direvoke")
        if agent is not None:
            return agent, "signed"
        # agent_id milik server lain (hasil enroll di instance berbeda). Jangan langsung
        # tolak: bila mode tanpa token aktif, lanjut ke pencocokan machine_id di bawah
        # supaya satu PC boleh push ke beberapa server. Revoke tetap ditolak di atas, dan
        # bila RANI_TOKENLESS_PUSH=0 header id asing tetap 401 (tidak bisa jadi bypass HMAC).
        identity = payload.get("identity") or {}
        if not settings.RANI_TOKENLESS_PUSH:
            log.warning(
                "push ditolak 401: X-Rani-Agent-Id %s tidak dikenal di server ini dan "
                "mode tanpa token dimatikan — machine_id=%s hostname=%s",
                agent_id, identity.get("machine_id"), identity.get("hostname"))
            raise HTTPException(status_code=401, detail="agent tidak dikenal/direvoke")
        log.warning(
            "agent_id %s tidak dikenal di server ini — diproses sebagai push tanpa token "
            "(machine_id=%s hostname=%s)",
            agent_id, identity.get("machine_id"), identity.get("hostname"))
        # signature milik server lain tidak bisa diverifikasi di sini; buang keduanya
        # supaya request diperlakukan sebagai push tanpa token yang sah.
        headers["agent_id"] = None
        headers["signature"] = None

    if not settings.RANI_TOKENLESS_PUSH:
        raise HTTPException(status_code=401,
                            detail="mode tanpa token dimatikan: kirim X-Rani-Agent-Id + "
                                   "X-Rani-Signature (raniPush --enroll)")

    identity = payload.get("identity") or {}
    machine_id = str(identity.get("machine_id") or "").strip()[:128] or None
    hostname = str(identity.get("hostname") or "").strip()[:128] or None
    if not machine_id and not hostname:
        raise HTTPException(status_code=422,
                            detail="payload tanpa identity.machine_id/hostname")

    agent = None
    if machine_id:
        agent = (await session.execute(
            select(Agent).where(Agent.machine_id == machine_id).limit(1)
        )).scalar_one_or_none()
    if agent is None and hostname:
        # Hanya agent mode langsung yang boleh dicocokkan lewat hostname.
        agent = (await session.execute(
            select(Agent).where(Agent.name == hostname, Agent.machine_id.is_(None),
                                Agent.secret_enc.is_(None)).limit(1)
        )).scalar_one_or_none()

    if agent is None:
        agent = Agent(name=hostname or machine_id or "unknown", machine_id=machine_id,
                      secret_enc=None, enrolled_at=now, last_seen=now,
                      agent_version=str(payload.get("agent_version") or "")[:32] or None,
                      config={"mode": "direct"})
        session.add(agent)
        await session.flush()
        log.info("agent langsung terdaftar: %s (%s)", agent.id, agent.name)
        await audit(session, request, actor="system", action="agent.autoregistered",
                    target=str(agent.id), details={"hostname": hostname,
                                                   "machine_id": machine_id})
        return agent, "direct"

    if agent.revoked_at is not None:
        raise HTTPException(status_code=401, detail="agent tidak dikenal/direvoke")
    return agent, "direct"


@router.post("/api/v1/ingest/push", status_code=202)
async def ingest_push(request: Request, response: Response,
                      session: AsyncSession = Depends(get_session)) -> dict:
    redis: Redis = request.app.state.redis
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="body kosong")
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="payload terlalu besar (maks 4MB)")

    headers = {
        "agent_id": request.headers.get("X-Rani-Agent-Id"),
        "digest": request.headers.get("X-Rani-Digest"),
        "signature": request.headers.get("X-Rani-Signature"),
        "timestamp": request.headers.get("X-Rani-Timestamp"),
        "nonce": request.headers.get("X-Rani-Nonce"),
    }
    required = (("digest", "X-Rani-Digest"), ("timestamp", "X-Rani-Timestamp"),
                ("nonce", "X-Rani-Nonce"))
    missing = [name for key, name in required if not headers[key]]
    if missing:
        raise HTTPException(status_code=400, detail=f"header wajib hilang: {', '.join(missing)}")
    # Id dan signature adalah pasangan: satu tanpa yang lain tidak bisa diverifikasi.
    if bool(headers["agent_id"]) != bool(headers["signature"]):
        raise HTTPException(status_code=400,
                            detail="X-Rani-Agent-Id dan X-Rani-Signature harus dikirim bersama")

    payload_sha = sha256_hex(raw)
    if not constant_eq(headers["digest"].removeprefix("sha256:"), payload_sha):
        raise HTTPException(status_code=401, detail="digest body tidak cocok")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalid: {exc.msg}") from exc

    version = payload.get("schema_version")
    validator = _SCHEMAS.get(version)
    if validator is None:
        raise HTTPException(status_code=422,
                            detail=f"schema_version {version!r} tidak didukung (server: 1)")
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        detail = [{"path": "/".join(str(p) for p in e.path), "error": e.message}
                  for e in errors[:10]]
        raise HTTPException(status_code=422, detail={"schema_errors": detail})

    agent, mode = await _resolve_agent(session, request, payload, headers)

    ts = _parse_ts(headers["timestamp"])
    skew = abs((datetime.now(timezone.utc) - ts).total_seconds())
    if skew > settings.RANI_TS_SKEW_S:
        raise HTTPException(status_code=401,
                            detail=f"timestamp skew {int(skew)}s di luar toleransi")

    if headers["signature"]:
        if not agent.secret_enc:
            raise HTTPException(status_code=401,
                                detail="agent ini tidak punya secret; jangan kirim signature")
        try:
            secret = decrypt_secret(agent.secret_enc, settings.RANI_INGEST_PEPPER)
        except ValueError as exc:
            log.error("secret agent %s tidak bisa didekripsi: %s", agent.id, exc)
            raise HTTPException(status_code=500,
                                detail="konfigurasi secret server rusak") from exc
        expected = hmac_hex(secret,
                            headers["timestamp"].encode() + headers["nonce"].encode() + raw)
        if not constant_eq(headers["signature"], expected):
            await audit(session, request, actor=f"agent:{agent.id}", action="ingest.rejected",
                        outcome="failure", details={"reason": "signature", "mode": mode})
            await session.commit()
            raise HTTPException(status_code=401, detail="signature tidak valid")

    nonce_key = f"rani:nonce:{agent.id}:{headers['nonce']}"
    if not await redis.set(nonce_key, "1", nx=True, ex=max(settings.RANI_TS_SKEW_S * 2, 600)):
        raise HTTPException(status_code=409, detail="nonce sudah dipakai (replay)")

    rl_key = f"rani:rl:{agent.id}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 60)
    if count > settings.RANI_RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="rate limit agent terlampaui")

    existing = (await session.execute(
        select(SoftwareReport).where(SoftwareReport.agent_id == agent.id,
                                     SoftwareReport.payload_sha == payload_sha)
    )).scalar_one_or_none()
    if existing is not None:
        response.headers["X-Rani-Idempotent"] = "1"
        return {"report_id": str(existing.id),
                "asset_id": str(existing.asset_id) if existing.asset_id else None,
                "next_interval_s": settings.RANI_DEFAULT_INTERVAL_S, "duplicate": True}

    pushed_at = None
    collected = payload.get("collected_at")
    if collected:
        try:
            pushed_at = _parse_ts(str(collected))
        except HTTPException:
            pushed_at = None

    report = SoftwareReport(agent_id=agent.id, pushed_at=pushed_at, payload_sha=payload_sha,
                            status="queued", raw=payload)
    session.add(report)
    agent.last_seen = datetime.now(timezone.utc)
    if payload.get("agent_version"):
        agent.agent_version = str(payload["agent_version"])[:32]
    identity = payload.get("identity") or {}
    if identity.get("machine_id") and not agent.machine_id:
        agent.machine_id = str(identity["machine_id"])[:128]
    await session.flush()
    await audit(session, request, actor=f"agent:{agent.id}", action="ingest.accepted",
                target=str(report.id), details={"bytes": len(raw), "mode": mode})
    # Commit DULU baru enqueue: worker tidak boleh melihat pesan sebelum row report ada.
    await session.commit()
    try:
        await enqueue_report(redis, str(report.id))
    except Exception as exc:  # pragma: no cover
        log.error("enqueue report %s gagal: %s (akan di-requeue oleh sweeper)", report.id, exc)

    return {"report_id": str(report.id), "asset_id": None, "agent_id": str(agent.id),
            "next_interval_s": settings.RANI_DEFAULT_INTERVAL_S}