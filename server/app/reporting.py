"""Custom report SQL: guard, role read-only, eksekusi aman, dan CSV.

Batas keamanan berlapis (lihat docs/reports.md):
1. Role DB terpisah `rani_report` — hanya SELECT, `default_transaction_read_only=on`,
   `statement_timeout` di level role. Ini batas keras: DML/DDL gagal walau guard lolos.
2. Guard aplikasi: hanya satu statement `SELECT`/`WITH`, tanpa `;` di tengah, tanpa
   DML/DDL dan tanpa fungsi berbahaya (pg_sleep, pg_read_file, dblink, ...).
3. Query dibungkus `SELECT * FROM (<sql>) q LIMIT max+1` supaya hasil selalu terbatas
   dan pemakaian memori terukur; kelebihan satu baris dipakai sebagai penanda truncated.
"""
from __future__ import annotations

import logging
import re
import time
import uuid as uuid_mod
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.db import SessionLocal
from app.models import Report

log = logging.getLogger("rani.reports")
settings = get_settings()

_ALLOWED_START = re.compile(r"^(select|with)\b", re.I)
_DANGEROUS = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|analyze|reindex|cluster|call|do|execute|exec|prepare|deallocate|listen|notify|"
    r"discard|lock|refresh)\b", re.I)
_BLOCKED_FUNCS = re.compile(
    r"\b(pg_sleep|pg_sleep_for|pg_sleep_until|pg_read_file|pg_read_binary_file|pg_ls_dir|"
    r"pg_stat_file|lo_import|lo_export|dblink|pg_terminate_backend|pg_cancel_backend|"
    r"pg_reload_conf|pg_rotate_logfile|set_config|pg_write_file)\b", re.I)
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ReportError(ValueError):
    """SQL ditolak guard atau gagal dieksekusi."""


def strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def validate_sql(sql: str) -> str:
    """Kembalikan SQL yang sudah dibersihkan (tanpa `;` akhir) atau raise ReportError."""
    if not sql or not sql.strip():
        raise ReportError("SQL kosong")
    body = sql.strip()
    core = strip_comments(body).strip()
    if not _ALLOWED_START.match(core):
        raise ReportError("hanya query SELECT atau WITH ... SELECT yang diizinkan")
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in strip_comments(body):
        raise ReportError("hanya satu statement; hapus ';' di tengah query "
                          "(dan jangan pakai ';' di dalam string literal)")
    stripped = strip_comments(body)
    match = _DANGEROUS.search(stripped)
    if match:
        raise ReportError(f"kata kunci terlarang: {match.group(1).upper()} "
                          "(report hanya boleh membaca data)")
    match = _BLOCKED_FUNCS.search(stripped)
    if match:
        raise ReportError(f"fungsi terlarang: {match.group(1)}()")
    return body


def _clean_db_error(exc: Exception) -> str:
    """Ambil pesan Postgres saja (buang nama kelas & boilerplate SQLAlchemy)."""
    raw = str(getattr(exc, "orig", exc) or exc)
    raw = re.sub(r"<class '[^']+'>:\s*", "", raw)
    raw = raw.split("[SQL:")[0].split("(Background on this error")[0]
    raw = " ".join(raw.split())
    return raw[:400] or "error tidak diketahui"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid_mod.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


# --------------------------------------------------------------------- engine --
_engine: AsyncEngine | None = None


def report_database_url() -> str:
    url = make_url(settings.DATABASE_URL)
    return url.set(username=settings.RANI_REPORT_DB_USER,
                   password=settings.RANI_REPORT_DB_PASSWORD or None).render_as_string(
        hide_password=False)


def get_report_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(report_database_url(), pool_size=2, max_overflow=0,
                                      pool_pre_ping=True)
    return _engine


async def dispose_report_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def ensure_report_role() -> bool:
    """Buat/perbarui role read-only + grant SELECT. Idempoten; dipanggil saat startup.

    Password berasal dari RANI_REPORT_DB_PASSWORD (bukan dibuat acak per proses) supaya
    dua worker uvicorn memakai kredensial yang sama.
    """
    if not settings.RANI_REPORT_DB_PASSWORD:
        log.warning("RANI_REPORT_DB_PASSWORD kosong — menu Reports dinonaktifkan")
        return False
    user = settings.RANI_REPORT_DB_USER
    if not _IDENT.match(user):
        log.error("RANI_REPORT_DB_USER tidak valid: %r", user)
        return False
    password = settings.RANI_REPORT_DB_PASSWORD.replace("'", "''")
    dbname = (make_url(settings.DATABASE_URL).database or "rani").replace('"', '""')
    schema = "rani_inventory"
    # Dua worker uvicorn start bersamaan: advisory xact lock membuat provisioning
    # serial, jadi tidak ada CREATE ROLE balapan (UniqueViolation).
    grants = [
        f'GRANT CONNECT ON DATABASE "{dbname}" TO {user}',
        f"GRANT USAGE ON SCHEMA {schema} TO {user}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {user}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {user}",
        # kredensial tidak boleh terbaca lewat report SQL (grant ALL TABLES di atas)
        f"REVOKE ALL ON {schema}.app_users FROM {user}",
        f"REVOKE ALL ON {schema}.auth_sessions FROM {user}",
        f"REVOKE ALL ON {schema}.enrollment_tokens FROM {user}",
    ]
    # batas keras di level database: sesi read-only + timeout
    role_settings = [
        f"ALTER ROLE {user} SET default_transaction_read_only = on",
        f"ALTER ROLE {user} SET statement_timeout = '{int(settings.RANI_REPORT_TIMEOUT_MS)}'",
        f"ALTER ROLE {user} SET idle_in_transaction_session_timeout = '15000'",
        f"ALTER ROLE {user} SET search_path = {schema}, public",
    ]
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(918273466)"))
            exists = (await session.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": user}
            )).scalar()
            if exists:
                await session.execute(text(
                    f"ALTER ROLE {user} WITH LOGIN PASSWORD '{password}'"))
            else:
                await session.execute(text(
                    f"CREATE ROLE {user} LOGIN PASSWORD '{password}'"))
            for stmt in (*grants, *role_settings):
                await session.execute(text(stmt))
            await session.commit()
        log.info("role report %s siap (read-only, timeout %sms)",
                 user, settings.RANI_REPORT_TIMEOUT_MS)
        return True
    except Exception as exc:  # noqa: BLE001 — startup tidak boleh mati karena fitur ini
        log.error("gagal menyiapkan role report: %s", exc)
        return False


SAMPLE_REPORTS = [
    ("Aset per sistem operasi",
     "Jumlah aset per OS — contoh report bawaan.",
     "SELECT os_caption, count(*) AS aset\n"
     "FROM assets\n"
     "GROUP BY os_caption\n"
     "ORDER BY aset DESC"),
    ("Top software (jumlah aset)",
     "20 software yang terpasang di paling banyak aset.",
     "SELECT s.name_raw AS software, count(DISTINCT s.asset_id) AS aset\n"
     "FROM software s\n"
     "WHERE s.present\n"
     "GROUP BY s.name_raw\n"
     "ORDER BY aset DESC\n"
     "LIMIT 20"),
    ("Aset tidak terlihat > 24 jam",
     "Aset yang statusnya offline atau last_seen lebih lama dari 24 jam.",
     "SELECT hostname, os_caption, status, last_seen\n"
     "FROM assets\n"
     "WHERE last_seen < now() - interval '24 hours'\n"
     "ORDER BY last_seen DESC"),
]


async def seed_sample_reports() -> int:
    """Isi 3 report contoh saat tabel masih kosong (idempoten)."""
    try:
        async with SessionLocal() as session:
            count = (await session.execute(select(func.count(Report.id)))).scalar_one()
            if count:
                return 0
            for name, description, sql in SAMPLE_REPORTS:
                session.add(Report(name=name, description=description + " (contoh)",
                                   sql_text=sql, is_shared=True))
            await session.commit()
        log.info("seed %d report contoh", len(SAMPLE_REPORTS))
        return len(SAMPLE_REPORTS)
    except Exception as exc:  # noqa: BLE001
        log.warning("gagal seed report contoh: %s", exc)
        return 0


# ----------------------------------------------------------------- execution --
async def run_report_sql(sql: str, *, max_rows: int | None = None) -> dict:
    """Jalankan query report. Raise ReportError untuk guard/DB error."""
    if not settings.RANI_REPORT_DB_PASSWORD:
        raise ReportError("fitur report belum aktif: set RANI_REPORT_DB_PASSWORD di .env "
                          "lalu restart api")
    body = validate_sql(sql)
    limit = max_rows or settings.RANI_REPORT_MAX_ROWS
    wrapped = f"SELECT * FROM (\n{body}\n) AS rani_report_q LIMIT {int(limit) + 1}"
    started = time.perf_counter()
    try:
        async with get_report_engine().connect() as conn:
            async with conn.begin():
                await conn.execute(text(
                    f"SET LOCAL statement_timeout = {int(settings.RANI_REPORT_TIMEOUT_MS)}"))
                result = await conn.execute(text(wrapped))
                columns = list(result.keys())
                raw_rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001 — pesan DB diteruskan ke penulis query
        raise ReportError(f"query gagal: {_clean_db_error(exc)}") from exc

    truncated = len(raw_rows) > limit
    rows = raw_rows[:limit]
    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "max_rows": limit,
        "duration_ms": duration_ms,
    }


def to_csv(columns: list[str], rows: list[list]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()