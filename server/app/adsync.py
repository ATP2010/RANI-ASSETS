"""Sync AD → RANI (F5.5). Delta: upsert anggota group terpetakan, nonaktifkan yang hilang.

- Advisory lock per connector (tidak overlap, manual maupun terjadwal).
- Run `partial` (ada group gagal dibaca) TIDAK menonaktifkan massal.
- AD user: role = union mapping group (menggantikan role lama) — kelola role lewat
  mapping, bukan lewat halaman user (akan tertimpa sync).
- User keluar semua group terpetakan → is_active=false + sesi dicabut (tidak dihapus).
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import directory as ad
from app.models import (AppUser, AppUserRole, AuthSession, DirectoryConnector,
                        DirectoryGroupRole, DirectorySyncRun, Role)
from starlette.concurrency import run_in_threadpool

log = logging.getLogger("rani.adsync")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _sync_lock_key(connector_id: uuid.UUID) -> str:
    return f"rani_ad_sync:{connector_id}"


async def sync_connector(session: AsyncSession, connector: DirectoryConnector,
                         *, mode: str = "manual", actor: str | None = None) -> dict:
    started = _utcnow()
    run = DirectorySyncRun(connector_id=connector.id, mode=mode, status="running",
                           started_at=started)
    session.add(run)
    await session.flush()

    lock_key = await _sync_lock_key(connector.id)
    locked = (await session.execute(
        text("select pg_try_advisory_xact_lock(hashtext(:key))"),
        {"key": lock_key})).scalar_one()
    if not locked:
        run.status = "failed"
        run.error = "sync sedang berjalan untuk connector ini"
        run.finished_at = _utcnow()
        await session.commit()
        return _run_dict(run)

    mappings = (await session.execute(
        select(DirectoryGroupRole, Role.slug)
        .join(Role, Role.id == DirectoryGroupRole.role_id)
        .where(DirectoryGroupRole.connector_id == connector.id,
               DirectoryGroupRole.enabled.is_(True))
    )).all()
    if not mappings:
        run.status = "failed"
        run.error = "tidak ada group AD yang dipetakan ke role; mapping dulu di tab Mapping"
        run.finished_at = _utcnow()
        connector.last_sync_at = run.finished_at
        connector.last_sync_status = "failed"
        connector.last_sync_error = run.error
        await _audit(session, actor, run, {"reason": "no_mapping"})
        await session.commit()
        return _run_dict(run)

    # Ambil anggota tiap group (sync di threadpool — ldap3 blocking)
    group_users: dict[str, list[dict]] = {}
    errors: list[str] = []
    for mapping, _slug in mappings:
        try:
            members = await run_in_threadpool(ad.search_group_members, connector,
                                              mapping.group_dn)
            group_users[ad.dn_key(mapping.group_dn)] = members
        except Exception as exc:  # noqa: BLE001 — group rusak tidak boleh menjatuhkan run
            log.warning("sync: group %s gagal dibaca: %s", mapping.group_dn, exc)
            errors.append(f"{mapping.group_name}: {exc}")

    # Gabung: key = guid (atau sam). Catat group yang dimiliki tiap user.
    merged: dict[str, dict] = {}
    for group_key, members in group_users.items():
        for m in members:
            sam = (m.get("sam") or "").lower()
            if not sam:
                continue
            key = m.get("guid") or f"sam:{sam}"
            entry = merged.setdefault(key, {**m, "groups": []})
            entry["groups"].append(group_key)

    now = _utcnow()
    created = updated = roles_changed = 0
    desired_usernames: set[str] = set()
    domain = (connector.domain or "").lower()

    roles_by_group = {ad.dn_key(m.group_dn): m.role_id for m, _ in mappings}
    for key, info in merged.items():
        sam = info["sam"].lower()
        username = f"{domain}\\{sam}"[:64]
        desired_usernames.add(username)
        desired_role_ids = sorted({roles_by_group[g] for g in info["groups"]
                                   if g in roles_by_group})
        user_row = await _upsert_ad_user(session, connector, info, username, now)
        if user_row[0] == "created":
            created += 1
        else:
            updated += 1
        if await _replace_roles(session, user_row[1], desired_role_ids):
            roles_changed += 1

    # Deaktivasi hanya bila SEMUA group berhasil dibaca (bukan partial)
    deactivated = 0
    if not errors:
        stale = (await session.execute(
            select(AppUser).where(
                AppUser.auth_source == "ad",
                AppUser.domain == connector.domain,
                AppUser.is_active.is_(True),
                AppUser.username.not_in(desired_usernames) if desired_usernames
                else AppUser.username.isnot(None)))).scalars().all()
        for stale_user in stale:
            stale_user.is_active = False
            stale_user.updated_at = now
            from app.access import revoke_sessions_for_user
            await revoke_sessions_for_user(session, stale_user.id)
            deactivated += 1

    run.users_seen = len(merged)
    run.created = created
    run.updated = updated
    run.deactivated = deactivated
    run.roles_changed = roles_changed
    run.status = "partial" if errors else "success"
    run.error = "; ".join(errors)[:2000] if errors else None
    run.finished_at = _utcnow()
    connector.last_sync_at = run.finished_at
    connector.last_sync_status = run.status
    connector.last_sync_error = run.error
    await _audit(session, actor, run, {
        "users_seen": run.users_seen, "created": created, "updated": updated,
        "deactivated": deactivated, "roles_changed": roles_changed,
        "partial_errors": errors,
    })
    await session.commit()
    return _run_dict(run)


async def _upsert_ad_user(session: AsyncSession, connector: DirectoryConnector,
                          info: dict, username: str, now: datetime):
    guid = info.get("guid")
    existing = None
    if guid:
        existing = (await session.execute(
            select(AppUser).where(AppUser.object_guid == guid))).scalar_one_or_none()
    if existing is None:
        existing = (await session.execute(
            select(AppUser).where(AppUser.username == username))).scalar_one_or_none()
    display = (info.get("display_name") or "").strip()[:128] or None
    email = (info.get("email") or "").strip()[:255] or None
    upn = (info.get("upn") or "").strip()[:255] or None
    if existing is None:
        user_row = AppUser(username=username, display_name=display, email=email,
                           password_hash=None, auth_source="ad",
                           domain=connector.domain, sam_account_name=info.get("sam"),
                           upn=upn, object_guid=guid, is_active=True,
                           created_at=now, updated_at=now, last_sync_at=now)
        session.add(user_row)
        await session.flush()
        return "created", user_row
    existing.username = username
    existing.display_name = display
    existing.email = email
    existing.upn = upn
    existing.sam_account_name = info.get("sam")
    existing.object_guid = guid or existing.object_guid
    existing.domain = connector.domain
    existing.is_active = True
    existing.auth_source = "ad"
    existing.last_sync_at = now
    existing.updated_at = now
    await session.flush()
    return "updated", existing


async def _replace_roles(session: AsyncSession, user_row: AppUser,
                         desired_role_ids: list) -> bool:
    current_rows = (await session.execute(
        select(AppUserRole.role_id).where(AppUserRole.user_id == user_row.id))).scalars().all()
    current = set(current_rows)
    desired = set(desired_role_ids)
    if current == desired:
        return False
    await session.execute(
        AppUserRole.__table__.delete().where(AppUserRole.user_id == user_row.id))
    for role_id in desired_role_ids:
        session.add(AppUserRole(user_id=user_row.id, role_id=role_id))
    return True


async def _audit(session, actor: str | None, run: DirectorySyncRun, details: dict) -> None:
    from app.models import AuditLog
    session.add(AuditLog(actor=actor, action="ad.sync",
                         target=str(run.connector_id),
                         outcome="success" if run.status == "success" else "failure",
                         details={"mode": run.mode, "status": run.status, **details},
                         created_at=_utcnow()))


def _run_dict(run: DirectorySyncRun) -> dict:
    duration_ms = None
    if run.started_at and run.finished_at:
        duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    return {
        "run_id": str(run.id), "status": run.status, "mode": run.mode,
        "users_seen": run.users_seen, "created": run.created, "updated": run.updated,
        "deactivated": run.deactivated, "roles_changed": run.roles_changed,
        "error": run.error,
        "duration_ms": duration_ms,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


async def due_connectors(session: AsyncSession) -> list[DirectoryConnector]:
    now = _utcnow()
    rows = (await session.execute(
        select(DirectoryConnector).where(
            DirectoryConnector.enabled.is_(True),
            DirectoryConnector.sync_interval_s > 0,
        ))).scalars().all()
    out = []
    for conn in rows:
        if conn.last_sync_at is None:
            out.append(conn)
            continue
        if (now - conn.last_sync_at).total_seconds() >= conn.sync_interval_s:
            out.append(conn)
    return out


async def connector_has_running_run(session: AsyncSession, connector_id) -> bool:
    since = _utcnow().timestamp() - 15 * 60
    row = (await session.execute(
        select(DirectorySyncRun.id).where(
            DirectorySyncRun.connector_id == connector_id,
            DirectorySyncRun.status == "running",
            DirectorySyncRun.started_at > datetime.fromtimestamp(since, tz=timezone.utc))
    )).scalar_one_or_none()
    return row is not None
