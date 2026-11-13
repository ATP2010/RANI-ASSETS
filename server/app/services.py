"""Service layer kecil: enrollment token & revoke agent (dipakai UI + API)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, EnrollmentToken
from app.security import new_token, sha256_hex


async def create_enrollment_token(session: AsyncSession, label: str | None,
                                 created_by: str | None, ttl_hours: int = 24
                                 ) -> tuple[EnrollmentToken, str]:
    raw = new_token(24)
    now = datetime.now(timezone.utc)
    row = EnrollmentToken(token_hash=sha256_hex(raw), label=(label or "")[:96] or None,
                          created_by=created_by, created_at=now,
                          expires_at=now + timedelta(hours=ttl_hours))
    session.add(row)
    await session.flush()
    return row, raw


async def revoke_agent(session: AsyncSession, agent_id, actor: str | None) -> Agent | None:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return None
    if agent.revoked_at is None:
        agent.revoked_at = datetime.now(timezone.utc)
    return agent