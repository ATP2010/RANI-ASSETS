"""Audit log sederhana (tanpa token/password)."""
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def audit(session: AsyncSession, request: Request | None, actor: str | None,
                action: str, target: str | None = None, outcome: str = "success",
                details: dict | None = None) -> None:
    session.add(AuditLog(
        actor=actor, action=action, target=target, outcome=outcome,
        details=details or {}, request_ip=client_ip(request) if request else None,
        created_at=datetime.now(timezone.utc),
    ))