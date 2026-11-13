"""Enrollment agent: token sekali-pakai → agent_id + agent_secret."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import get_settings
from app.crypto import encrypt_secret
from app.db import get_session
from app.models import Agent, EnrollmentToken
from app.security import new_token, sha256_hex

router = APIRouter(tags=["enroll"])
settings = get_settings()


class EnrollRequest(BaseModel):
    token: str = Field(min_length=8)
    machine_id: str | None = None
    hostname: str = Field(min_length=1, max_length=255)
    agent_version: str | None = None


class EnrollResponse(BaseModel):
    agent_id: str
    agent_secret: str
    next_interval_s: int


@router.post("/api/v1/enroll", response_model=EnrollResponse)
async def enroll(body: EnrollRequest, request: Request,
                 session: AsyncSession = Depends(get_session)) -> EnrollResponse:
    now = datetime.now(timezone.utc)
    token = (await session.execute(
        select(EnrollmentToken).where(EnrollmentToken.token_hash == sha256_hex(body.token))
    )).scalar_one_or_none()
    if token is None:
        raise HTTPException(status_code=401, detail="token tidak dikenal")
    if token.used_at is not None:
        raise HTTPException(status_code=409, detail="token sudah dipakai")
    if token.expires_at and token.expires_at <= now:
        raise HTTPException(status_code=410, detail="token kedaluwarsa")

    secret = new_token(32)
    agent = Agent(name=body.hostname[:128], machine_id=(body.machine_id or None),
                  secret_enc=encrypt_secret(secret, settings.RANI_INGEST_PEPPER),
                  enrolled_at=now, last_seen=now, agent_version=body.agent_version,
                  config={"interval_s": settings.RANI_DEFAULT_INTERVAL_S})
    session.add(agent)
    await session.flush()

    token.used_at = now
    token.used_by_agent = agent.id
    await audit(session, request, actor=f"token:{token.label or token.id}",
                action="agent.enrolled", target=str(agent.id),
                details={"hostname": body.hostname, "machine_id": body.machine_id})
    await session.commit()
    return EnrollResponse(agent_id=str(agent.id), agent_secret=secret,
                          next_interval_s=settings.RANI_DEFAULT_INTERVAL_S)