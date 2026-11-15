"""Halaman UI custom report (menu Reports) + export CSV.

Alur mengikuti Lansweeper Classic: Reports → Create New Report → tulis/ubah SQL →
Save & Run → hasil tampil sebagai grid dengan filter per kolom dan tombol export.
SQL dieksekusi read-only lewat role DB terpisah (lihat app/reporting.py).
"""
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.config import get_settings
from app.db import get_session
from app.deps import require_perm
from app.models import AppUser, Report
from app.queries import get_report, list_reports
from app.reporting import ReportError, run_report_sql, to_csv, validate_sql
from app.templating import templates

settings = get_settings()

log = logging.getLogger("rani.reports.ui")
router = APIRouter(include_in_schema=False)

MAX_NAME = 128
MAX_DESC = 2000

EXAMPLE_QUERIES = [
    ("Aset per sistem operasi",
     "SELECT os_caption, count(*) AS aset\n"
     "FROM assets\n"
     "GROUP BY os_caption\n"
     "ORDER BY aset DESC;"),
    ("Top 20 software (jumlah aset)",
     "SELECT s.name_raw AS software, count(DISTINCT s.asset_id) AS aset\n"
     "FROM software s\n"
     "WHERE s.present\n"
     "GROUP BY s.name_raw\n"
     "ORDER BY aset DESC\n"
     "LIMIT 20;"),
    ("Aset offline & terakhir terlihat",
     "SELECT hostname, os_caption, last_seen\n"
     "FROM assets\n"
     "WHERE status = 'offline'\n"
     "ORDER BY last_seen DESC;"),
    ("Software terpasang pada aset tertentu",
     "SELECT a.hostname, s.name_raw AS software, s.version\n"
     "FROM software s\n"
     "JOIN assets a ON a.id = s.asset_id\n"
     "WHERE s.present AND a.hostname ILIKE '%PC%'\n"
     "ORDER BY a.hostname, s.name_raw\n"
     "LIMIT 200;"),
    ("Agent yang belum push 24 jam",
     "SELECT name, machine_id, last_seen\n"
     "FROM agents\n"
     "WHERE last_seen < now() - interval '24 hours'\n"
     "ORDER BY last_seen;"),
]


def _can_edit(report: Report | None, user: AppUser) -> bool:
    if "reports.manage" in getattr(user, "perm_set", set()):
        return True
    return report is not None and report.owner_id == user.id


def _parse_form(name: str, description: str, sql_text: str) -> tuple[str, str, str, list[str]]:
    errors: list[str] = []
    clean_name = (name or "").strip()
    clean_desc = (description or "").strip()[:MAX_DESC]
    body = ""
    if not clean_name:
        errors.append("Nama report wajib diisi.")
    elif len(clean_name) > MAX_NAME:
        errors.append(f"Nama report maksimal {MAX_NAME} karakter.")
    try:
        body = validate_sql(sql_text or "")
    except ReportError as exc:
        errors.append(str(exc))
    return clean_name, clean_desc, body, errors


def _page(request: Request, user: AppUser, report: Report | None, owner: str | None,
          *, run: bool = False, error: str | None = None, values: dict | None = None):
    return templates.TemplateResponse(request, "report_form.html", {
        "user": user, "active": "reports", "report": report, "owner": owner,
        "examples": EXAMPLE_QUERIES, "run_now": run, "error": error,
        "can_edit": _can_edit(report, user) if report else "reports.manage" in getattr(user, "perm_set", set()),
        "values": values or {},
        "max_rows": settings.RANI_REPORT_MAX_ROWS,
        "timeout_ms": settings.RANI_REPORT_TIMEOUT_MS,
    })


@router.get("/reports")
async def reports_page(request: Request, session: AsyncSession = Depends(get_session),
                       user: AppUser = Depends(require_perm("reports.view"))):
    return templates.TemplateResponse(request, "reports.html", {
        "user": user, "active": "reports", "rows": await list_reports(session, user),
        "can_create": "reports.manage" in getattr(user, "perm_set", set()),
    })


@router.get("/reports/new")
async def report_new(request: Request,
                     user: AppUser = Depends(require_perm("reports.manage"))):
    return _page(request, user, None, None, values={"name": "", "description": "",
                                                    "sql_text": ""})


@router.post("/reports/new")
async def report_create(request: Request, name: str = Form(""), description: str = Form(""),
                        sql_text: str = Form(""), action: str = Form("save"),
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("reports.manage"))):
    clean_name, clean_desc, body, errors = _parse_form(name, description, sql_text)
    if errors:
        return _page(request, user, None, None, error=" ".join(errors),
                     values={"name": name, "description": description, "sql_text": sql_text})

    report = Report(name=clean_name, description=clean_desc or None, sql_text=body,
                    owner_id=user.id, is_shared=True)
    session.add(report)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return _page(request, user, None, None,
                     error=f"Nama report “{clean_name}” sudah dipakai.",
                     values={"name": name, "description": description, "sql_text": sql_text})
    await audit(session, request, actor=user.username, action="report.create",
                target=str(report.id), details={"name": clean_name})
    await session.commit()
    suffix = "?run=1" if action == "run" else "?saved=1"
    return RedirectResponse(f"/reports/{report.id}{suffix}", status_code=303)


@router.get("/reports/{report_id}")
async def report_detail(report_id: uuid.UUID, request: Request, run: int = 0,
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("reports.view"))):
    found = await get_report(session, report_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail="report tidak ditemukan")
    return _page(request, user, found["report"], found["owner"], run=bool(run))


@router.post("/reports/{report_id}/save")
async def report_save(report_id: uuid.UUID, request: Request,
                      name: str = Form(""), description: str = Form(""),
                      sql_text: str = Form(""), action: str = Form("save"),
                      session: AsyncSession = Depends(get_session),
                      user: AppUser = Depends(require_perm("reports.view"))):
    found = await get_report(session, report_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail="report tidak ditemukan")
    report = found["report"]
    if not _can_edit(report, user):
        raise HTTPException(status_code=403, detail="hanya pemilik report atau admin")

    clean_name, clean_desc, body, errors = _parse_form(name, description, sql_text)
    if errors:
        return _page(request, user, report, found["owner"], error=" ".join(errors),
                     values={"name": name, "description": description, "sql_text": sql_text})

    report.name = clean_name
    report.description = clean_desc or None
    report.sql_text = body
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return _page(request, user, report, found["owner"],
                     error=f"Nama report “{clean_name}” sudah dipakai.",
                     values={"name": name, "description": description, "sql_text": sql_text})
    await audit(session, request, actor=user.username, action="report.save",
                target=str(report.id), details={"name": clean_name})
    await session.commit()
    suffix = "?run=1" if action == "run" else "?saved=1"
    return RedirectResponse(f"/reports/{report.id}{suffix}", status_code=303)


@router.post("/reports/{report_id}/delete")
async def report_delete(report_id: uuid.UUID, request: Request,
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("reports.view"))):
    found = await get_report(session, report_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail="report tidak ditemukan")
    report = found["report"]
    if not _can_edit(report, user):
        raise HTTPException(status_code=403, detail="hanya pemilik report atau admin")
    name = report.name
    await session.delete(report)
    await audit(session, request, actor=user.username, action="report.delete",
                target=str(report_id), details={"name": name})
    await session.commit()
    return RedirectResponse("/reports", status_code=303)


@router.get("/reports/{report_id}/export.csv")
async def report_export(report_id: uuid.UUID,
                        session: AsyncSession = Depends(get_session),
                        user: AppUser = Depends(require_perm("reports.export"))):
    found = await get_report(session, report_id, user)
    if found is None:
        raise HTTPException(status_code=404, detail="report tidak ditemukan")
    report = found["report"]
    try:
        result = await run_report_sql(report.sql_text)
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = to_csv(result["columns"], result["rows"])
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in report.name)[:60]
    return StreamingResponse(iter([payload]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      f'attachment; filename="rani-{safe or "report"}.csv"'})