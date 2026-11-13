"""RANI API entrypoint."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.api import auth, data, enroll, ingest, system, ui
from app.config import get_settings
from app.db import SessionLocal, dispose_engine
from app.models import AppUser
from app.security import hash_password, new_token
from app.version import VERSION
from app.ws import listen_forever

log = logging.getLogger("rani")
settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


async def seed_admin() -> None:
    async with SessionLocal() as session:
        # Serialisasi antar proses uvicorn: tanpa ini dua worker bisa balapan insert.
        await session.execute(text("select pg_advisory_xact_lock(918273465)"))
        count = (await session.execute(select(func.count(AppUser.id)))).scalar_one()
        if count:
            await session.commit()
            return
        password = settings.RANI_ADMIN_PASSWORD or new_token(12)
        session.add(AppUser(username=settings.RANI_ADMIN_USER, display_name="Administrator",
                            password_hash=hash_password(password), role="admin"))
        await session.commit()
        if settings.RANI_ADMIN_PASSWORD:
            log.warning("seeded admin user %r (password dari RANI_ADMIN_PASSWORD)",
                        settings.RANI_ADMIN_USER)
        else:
            log.warning("seeded admin user %r dengan password acak: %s  ← simpan sekarang",
                        settings.RANI_ADMIN_USER, password)


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis = redis
    listener = asyncio.create_task(listen_forever(redis))
    await seed_admin()
    try:
        yield
    finally:
        listener.cancel()
        try:
            await redis.aclose()
        except Exception:
            pass
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
    app.include_router(ui.router)

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