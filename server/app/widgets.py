"""Widget dashboard custom — sumber data: report SQL tersimpan (read-only).

Dashboard `/` menampilkan widget yang enabled. Widget yang laporannya dihapus
menampilkan kartu error (tautan ke Setup → Dashboard untuk memperbaiki).
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DashboardWidget, Report
from app.reporting import ReportError, run_report_sql

BUILTIN_KINDS: list[tuple[str, str]] = [
    ("kpi-total", "Bawaan: Total aset"),
    ("kpi-online", "Bawaan: Aset online"),
    ("kpi-offline", "Bawaan: Aset offline"),
    ("kpi-software", "Bawaan: Judul software + instalasi aktif"),
    ("chart-os", "Bawaan: Donut — distribusi OS"),
    ("chart-status", "Bawaan: Donut — status aset"),
    ("chart-software", "Bawaan: Bar — Top software (jumlah aset)"),
    ("chart-trend", "Bawaan: Area — push masuk 24 jam"),
    ("recent-events", "Bawaan: Tabel — perubahan software terakhir"),
]

BUILTIN_KIND_SET = {k for k, _ in BUILTIN_KINDS}

WIDGET_KINDS: list[tuple[str, str]] = [
    *BUILTIN_KINDS,
    ("stat", "Angka besar — total kolom nilai"),
    ("donut", "Donut — kategori → nilai"),
    ("bar", "Bar chart — kategori → nilai"),
    ("line", "Line chart — urutan baris"),
    ("table", "Tabel data — baris & kolom mentah"),
]

WIDGET_WIDTHS: list[tuple[str, str]] = [
    ("col-lg-3", "Kecil (¼ grid)"),
    ("col-md-6 col-xl-3", "KPI responsif (½ tablet / ¼ desktop)"),
    ("col-lg-4", "Sedang (⅓ grid) — default"),
    ("col-lg-6", "Setengah (½ grid)"),
    ("col-lg-7", "Lebar (7/12)"),
    ("col-lg-5", "Medium (5/12)"),
    ("col-lg-12", "Penuh"),
]

_KIND_LABELS = dict(WIDGET_KINDS)


def _num(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return value


def _fmt_number(value: float) -> str:
    n = value
    if n == int(n):
        return f"{int(n):,}".replace(",", ".")
    return f"{n:,.2f}".replace(",", ".")


async def load_enabled(session: AsyncSession) -> list[dict]:
    """Semua widget enabled, terurut, dengan statistik/kolom siap render."""
    rows = list((await session.execute(
        select(DashboardWidget).where(DashboardWidget.enabled.is_(True))
        .order_by(DashboardWidget.sort_order.asc(), DashboardWidget.title.asc())
    )).scalars().all())
    out: list[dict] = []
    for row in rows:
        item = {
            "id": str(row.id),
            "title": row.title,
            "kind": row.kind,
            "kind_label": _KIND_LABELS.get(row.kind, row.kind),
            "width": row.width,
            "x_col": row.x_col,
            "y_col": row.y_col,
            "is_builtin": row.kind in BUILTIN_KIND_SET,
            "report_id": str(row.report_id) if row.report_id else None,
            "report_name": None,
            "x_index": None,
            "y_index": None,
            "columns": [],
            "rows": [],
            "labels": [],
            "chart_values": [],
            "total": 0.0,
            "total_fmt": "0",
            "error": None,
        }
        if row.kind in BUILTIN_KIND_SET:
            out.append(item)
            continue
        if row.report_id is None:
            item["error"] = "laporan sumber dihapus — perbaiki di Setup → Dashboard"
            out.append(item)
            continue
        report = await session.get(Report, row.report_id)
        item["report_name"] = report.name if report else None
        if report is None:
            item["error"] = "laporan sumber dihapus — perbaiki di Setup → Dashboard"
            out.append(item)
            continue
        try:
            result = await run_report_sql(report.sql_text)
        except ReportError as exc:
            item["error"] = str(exc)[:300]
            out.append(item)
            continue
        cols = list(result["columns"])
        rows_data = result["rows"]
        xi = cols.index(row.x_col) if row.x_col in cols else 0
        yi = cols.index(row.y_col) if row.y_col in cols else (1 if len(cols) > 1 else 0)
        item.update({
            "columns": cols,
            "x_index": xi, "y_index": yi,
            "x_col": cols[xi], "y_col": cols[yi],
        })
        if row.kind == "table":
            item["rows"] = [[_cell(v) for v in r] for r in rows_data[:100]]
        else:
            item["labels"] = [str(_cell(r[xi]) if r[xi] is not None else "—") for r in rows_data[:200]]
            item["chart_values"] = [_num(r[yi]) for r in rows_data[:200]]
            item["total"] = sum(item["chart_values"])
            item["total_fmt"] = _fmt_number(item["total"])
        out.append(item)
    return out


async def preview_report(session: AsyncSession, report_id) -> dict:
    """Kolom + 10 baris pertama + error (untuk form Setup → Dashboard)."""
    empty = {"columns": [], "rows": [], "error": None}
    if not report_id:
        return empty
    report = await session.get(Report, report_id)
    if report is None:
        empty["error"] = "report tidak ditemukan"
        return empty
    try:
        result = await run_report_sql(report.sql_text)
    except ReportError as exc:
        empty["error"] = str(exc)[:300]
        return empty
    cols = list(result["columns"])
    rows = [[_cell(v) for v in r] for r in result["rows"][:10]]
    return {"columns": cols, "rows": rows, "error": None,
            "name": report.name, "row_count": result.get("row_count")}
