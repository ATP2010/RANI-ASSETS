"""API custom report: eksekusi SQL read-only (JSON) + CSV.

Halaman UI-nya ada di `app/api/reports_ui.py`; mesin query + guard di `app/reporting.py`.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.db import get_session
from app.deps import require_perm
from app.models import AppUser
from app.queries import get_report
from app.reporting import ReportError, run_report_sql

log = logging.getLogger("rani.reports.api")
router = APIRouter(tags=["reports"])


@router.post("/api/v1/reports/{report_id}/run")
async def run_report(report_id: uuid.UUID, request: Request,
                     session: AsyncSession = Depends(get_session),
                     user: AppUser = Depends(require_perm("reports.run"))) -> dict:
    found = await get_report(session, report_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail="report tidak ditemukan")
    report = found["report"]

    try:
        result = await run_report_sql(report.sql_text)
    except ReportError as exc:
        report.last_error = str(exc)[:1000]
        await audit(session, request, actor=user.username, action="report.run",
                    target=str(report.id), outcome="failure",
                    details={"error": str(exc)[:300]})
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    report.last_run_at = datetime.now(timezone.utc)
    report.last_run_ms = result["duration_ms"]
    report.last_run_rows = result["row_count"]
    report.last_error = None
    await audit(session, request, actor=user.username, action="report.run",
                target=str(report.id),
                details={"rows": result["row_count"], "ms": result["duration_ms"],
                         "truncated": result["truncated"]})
    await session.commit()

    return {"report_id": str(report.id), "name": report.name, **result}