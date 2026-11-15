"""RANI API entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.api import (agents_ui, auth, data, directory_ui, downloads, enroll, ingest,
                     network, reports, reports_ui, scan, setup_ui, system, ui, users)
from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.models import AppUser, AppUserRole, Role
from app.permissions import DEFAULT_ROLES
from app.reporting import dispose_report_engine, ensure_report_role, seed_sample_reports
from app.security import hash_password, new_token
from app.version import VERSION
from app.ws import listen_forever

log = logging.getLogger("rani")
settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


async def ensure_builtin_roles(session) -> None:
    """Seed role bawaan (idempotent) — jaring pengaman selain migration 0006."""
    now = datetime.now(timezone.utc)
    for spec in DEFAULT_ROLES:
        exists = (await session.execute(
            select(Role.id).where(Role.slug == spec["slug"]))).scalar_one_or_none()
        if exists is None:
            session.add(Role(slug=spec["slug"], name=spec["name"],
                             description=spec["description"],
                             permissions=spec["permissions"], is_builtin=True,
                             created_at=now, updated_at=now))


async def seed_admin() -> None:
    async with SessionLocal() as session:
        # Serialisasi antar proses uvicorn: tanpa ini dua worker bisa balapan insert.
        await session.execute(text("select pg_advisory_xact_lock(918273465)"))
        await ensure_builtin_roles(session)
        count = (await session.execute(select(func.count(AppUser.id)))).scalar_one()
        admin_role = (await session.execute(
            select(Role).where(Role.slug == "admin"))).scalar_one()
        if count == 0:
            password = settings.RANI_ADMIN_PASSWORD or new_token(12)
            user = AppUser(username=settings.RANI_ADMIN_USER,
                           display_name="Administrator",
                           password_hash=hash_password(password),
                           auth_source="local")
            session.add(user)
            await session.flush()
            session.add(AppUserRole(user_id=user.id, role_id=admin_role.id))
            await session.commit()
            if settings.RANI_ADMIN_PASSWORD:
                log.warning("seeded admin user %r (password dari RANI_ADMIN_PASSWORD)",
                            settings.RANI_ADMIN_USER)
            else:
                log.warning("seeded admin user %r dengan password acak: %s  ← simpan sekarang",
                            settings.RANI_ADMIN_USER, password)
            return
        # Instalasi lama: pastikan minimal satu user punya role admin (jaring backfill).
        has_admin = (await session.execute(
            select(func.count(AppUserRole.user_id))
            .join(Role, Role.id == AppUserRole.role_id)
            .where(Role.slug == "admin"))).scalar_one()
        if not has_admin:
            first = (await session.execute(
                select(AppUser).order_by(AppUser.created_at).limit(1))).scalar_one()
            session.add(AppUserRole(user_id=first.id, role_id=admin_role.id))
            await session.commit()
            log.warning("installed default: user pertama %r diberi role admin", first.username)
        else:
            await session.commit()


async def ad_sync_loop() -> None:
    """Cek connector AD yang jatuh tempo tiap 60 detik; sync mode=interval."""
    from app.adsync import connector_has_running_run, due_connectors, sync_connector

    while True:
        await asyncio.sleep(60)
        try:
            async with SessionLocal() as session:
                due = await due_connectors(session)
                for conn in due:
                    if await connector_has_running_run(session, conn.id):
                        continue
                    log.info("ad sync (interval): connector %r domain %r",
                             conn.name, conn.domain)
                    try:
                        await sync_connector(session, conn, mode="interval",
                                             actor="system")
                    except Exception:
                        log.exception("ad sync connector %r gagal", conn.name)
        except Exception:
            log.exception("ad sync loop gagal")


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis
    listener = asyncio.create_task(listen_forever(redis))
    ad_task = asyncio.create_task(ad_sync_loop())
    await seed_admin()
    app.state.reports_enabled = await ensure_report_role()
    if app.state.reports_enabled:
        await seed_sample_reports()
    try:
        yield
    finally:
        listener.cancel()
        ad_task.cancel()
        try:
            await redis.aclose()
        except Exception:
            pass
        await dispose_report_engine()
        await dispose_engine()


def create_app() -> FastAPI:
    logging.basicConfig(level=getattr(logging, settings.RANI_LOG_LEVEL.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    app = FastAPI(title="RANI", version=VERSION, lifespan=lifespan,
                  docs_url="/api/docs" if settings.RANI_ENV != "production" else None,
                  openapi_url="/api/openapi.json" if settings.RANI_ENV != "production" else None)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(enroll.router)
    app.include_router(ingest.router)
    app.include_router(data.router)
    app.include_router(agents_ui.router)
    app.include_router(scan.router)
    app.include_router(network.router)
    app.include_router(ui.router)
    app.include_router(reports_ui.router)
    app.include_router(reports.router)
    # directory_ui harus sebelum users: /users/directory vs /users/{user_id}
    app.include_router(directory_ui.router)
    app.include_router(directory_ui.api_router)
    app.include_router(setup_ui.router)
    app.include_router(users.router)
    app.include_router(users.api_router)
    app.include_router(downloads.router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        accept = request.headers.get("accept", "")
        if exc.status_code in (401, 403) and "text/html" in accept:
            return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(detail, status_code=exc.status_code)
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    return app


app = create_app()