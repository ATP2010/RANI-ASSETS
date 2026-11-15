"""ORM models — schema tunggal `rani_inventory` (analysis §3.5)."""
import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Identity,
                        Index, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SCHEMA = "rani_inventory"
UUID_PK = UUID(as_uuid=True)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID_PK, primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class AppUser(Base):
    __tablename__ = "app_users"
    __table_args__ = {"schema": SCHEMA}

    id = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)  # AD: 'domain\\sam' (lowercase)
    display_name: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str | None] = mapped_column(Text)  # NULL untuk user AD
    auth_source: Mapped[str] = mapped_column(String(8), default="local")  # local|ad
    domain: Mapped[str | None] = mapped_column(String(64))  # NetBIOS, hanya AD
    sam_account_name: Mapped[str | None] = mapped_column(String(64))
    upn: Mapped[str | None] = mapped_column(String(255))
    object_guid: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = {"schema": SCHEMA}

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(raw)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.app_users.id",
                                                          ondelete="CASCADE"))
    created_at = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(64))
    auth_source: Mapped[str] = mapped_column(String(8), default="local")  # local|ad


class Role(Base):
    """Role login RANI (bawaan atau custom). Permission = list kunci `modul.aksi`."""
    __tablename__ = "roles"
    __table_args__ = {"schema": SCHEMA}

    id = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(96))
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list] = mapped_column(JSONB, default=list)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppUserRole(Base):
    __tablename__ = "app_user_roles"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True)


class DirectoryConnector(Base):
    """Connector AD/LDAP (satu baris = satu domain). Bind password terenkripsi Fernet."""
    __tablename__ = "directory_connectors"
    __table_args__ = {"schema": SCHEMA}

    id = _uuid_pk()
    name: Mapped[str] = mapped_column(String(96))
    domain: Mapped[str] = mapped_column(String(64))  # NetBIOS, mis. CORP
    domain_fqdn: Mapped[str] = mapped_column(String(255))  # mis. corp.local
    url: Mapped[str] = mapped_column(String(255))  # ldaps://dc01:636
    use_ldaps: Mapped[bool] = mapped_column(Boolean, default=True)
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_cert_pem: Mapped[str | None] = mapped_column(Text)
    bind_dn: Mapped[str] = mapped_column(String(255))
    bind_password_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(pepper), write-only
    base_dn: Mapped[str] = mapped_column(String(255))
    user_filter: Mapped[str] = mapped_column(String(512), default=(
        "(&(objectCategory=person)(objectClass=user)"
        "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"))
    group_filter: Mapped[str] = mapped_column(String(255), default="(objectClass=group)")
    nested_groups: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_interval_s: Mapped[int] = mapped_column(Integer, default=3600)  # 0 = manual saja
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(16))  # success|partial|failed
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    created_at = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DirectoryGroupRole(Base):
    """Mapping group AD -> role RANI."""
    __tablename__ = "directory_group_roles"
    __table_args__ = (
        UniqueConstraint("connector_id", "group_dn", name="uq_directory_group_roles_conn_dn"),
        Index(f"ix_{SCHEMA}_dgr_role", "role_id"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    connector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.directory_connectors.id", ondelete="CASCADE"), index=True)
    group_dn: Mapped[str] = mapped_column(String(512))
    group_name: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.roles.id", ondelete="RESTRICT"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class DirectorySyncRun(Base):
    __tablename__ = "directory_sync_runs"
    __table_args__ = (
        Index(f"ix_{SCHEMA}_dsr_connector_started", "connector_id", "started_at"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    connector_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.directory_connectors.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16), default="manual")  # manual|interval
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|partial|failed
    users_seen: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    deactivated: Mapped[int] = mapped_column(Integer, default=0)
    roles_changed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(96))
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    request_ip: Mapped[str | None] = mapped_column(String(64))
    created_at = _now()


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"
    __table_args__ = {"schema": SCHEMA}

    id = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str | None] = mapped_column(String(96))
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at = _now()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_agent: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = {"schema": SCHEMA}

    id = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128))
    machine_id: Mapped[str | None] = mapped_column(String(128), index=True)
    secret_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(pepper); NULL = agent mode langsung
    enrolled_at = _now()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)


class Report(Base):
    """Custom report: SQL SELECT yang ditulis user, dijalankan sebagai role read-only."""
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("name", name="uq_reports_name"),
        Index(f"ix_{SCHEMA}_reports_updated", "updated_at"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    sql_text: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.app_users.id", ondelete="SET NULL"), index=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_ms: Mapped[int | None] = mapped_column(Integer)
    last_run_rows: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index(f"ix_{SCHEMA}_assets_hostname", "hostname"),
        Index(f"ix_{SCHEMA}_assets_serial", "serial"),
        Index(f"ix_{SCHEMA}_assets_mac", "primary_mac"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_type: Mapped[str] = mapped_column(String(24), default="computer")
    hostname: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255))
    machine_id: Mapped[str | None] = mapped_column(String(128), index=True)
    os_family: Mapped[str | None] = mapped_column(String(24))
    os_caption: Mapped[str | None] = mapped_column(String(255))
    os_version: Mapped[str | None] = mapped_column(String(64))
    os_build: Mapped[str | None] = mapped_column(String(64))
    serial: Mapped[str | None] = mapped_column(String(128))
    vendor: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(191))
    primary_mac: Mapped[str | None] = mapped_column(String(32))
    ip_last: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="online")  # online|offline
    first_seen = _now()
    last_seen = _now()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK, index=True)
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)


class AssetSource(Base):
    __tablename__ = "asset_sources"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(24))          # agent|snmp
    matched_on: Mapped[str] = mapped_column(String(24))      # machine_id|serial|mac|hostname|new
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    ts = _now()


class SoftwareReport(Base):
    """Satu push = satu report. Raw payload retensi 90 hari."""
    __tablename__ = "software_reports"
    __table_args__ = (
        UniqueConstraint("agent_id", "payload_sha", name="uq_software_reports_agent_sha"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                                 ondelete="SET NULL"),
                                                      index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.agents.id",
                                                          ondelete="CASCADE"), index=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at = _now()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|processed|failed|duplicate
    error: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB)


class Software(Base):
    __tablename__ = "software"
    __table_args__ = (
        UniqueConstraint("asset_id", "name_norm", name="uq_software_asset_name"),
        Index(f"ix_{SCHEMA}_software_name_norm", "name_norm"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    name_norm: Mapped[str] = mapped_column(String(255))
    name_raw: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(96))
    vendor: Mapped[str | None] = mapped_column(String(191))
    install_date: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(32))
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen = _now()
    last_seen = _now()


class SoftwareEvent(Base):
    __tablename__ = "software_events"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    software_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    event: Mapped[str] = mapped_column(String(16))  # installed|uninstalled|changed
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                         index=True)


class HwComponent(Base):
    __tablename__ = "hw_components"
    __table_args__ = (
        UniqueConstraint("asset_id", "class_", "key", name="uq_hw_components_asset_class_key"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    class_: Mapped[str] = mapped_column("class_", String(24))
    key: Mapped[str] = mapped_column(String(255))
    attrs: Mapped[dict] = mapped_column(JSONB, default=dict)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen = _now()
    last_seen = _now()


class UserSeen(Base):
    __tablename__ = "users_seen"
    __table_args__ = (
        UniqueConstraint("asset_id", "username", "role", name="uq_users_seen_asset_user_role"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(191))
    role: Mapped[str] = mapped_column(String(24))  # primary|logged_on|local_admin
    last_seen = _now()


class SecurityState(Base):
    __tablename__ = "security_state"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    av_product: Mapped[str | None] = mapped_column(String(128))
    av_ok: Mapped[bool | None] = mapped_column(Boolean)
    firewall: Mapped[dict] = mapped_column(JSONB, default=dict)
    disk_encryption: Mapped[str | None] = mapped_column(String(24))
    tpm_version: Mapped[str | None] = mapped_column(String(16))
    secure_boot: Mapped[bool | None] = mapped_column(Boolean)
    pending_reboot: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class NetworkInterface(Base):
    __tablename__ = "network_interfaces"
    __table_args__ = (
        UniqueConstraint("asset_id", "name", name="uq_network_interfaces_asset_name"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.assets.id",
                                                          ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(96))
    mac: Mapped[str | None] = mapped_column(String(32))
    ipv4: Mapped[str | None] = mapped_column(String(64))
    ipv6: Mapped[str | None] = mapped_column(String(64))
    mask: Mapped[str | None] = mapped_column(String(64))
    gateway: Mapped[str | None] = mapped_column(String(64))
    dns: Mapped[list] = mapped_column(JSONB, default=list)
    dhcp: Mapped[bool | None] = mapped_column(Boolean)
    speed_mbps: Mapped[float | None] = mapped_column(Float)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen = _now()


class ScanGroup(Base):
    """Grup IP untuk scan SNMP: daftar CIDR/range + kredensial community (terenkripsi)."""
    __tablename__ = "scan_groups"
    __table_args__ = (
        UniqueConstraint("name", name="uq_scan_groups_name"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    ranges: Mapped[list] = mapped_column(JSONB, default=list)   # ["10.0.0.0/24", "10.0.1.5-10.0.1.20"]
    snmp_version: Mapped[str] = mapped_column(String(8), default="2c")  # 1 | 2c
    community_enc: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer, default=161)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fdb_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # port map (bridge FDB)
    created_at = _now()
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_status: Mapped[str | None] = mapped_column(String(32))


class ScanOid(Base):
    """Custom OID (gaya Lansweeper Custom OID Scanning): label + OID, filter vendor/model."""
    __tablename__ = "scan_oids"
    __table_args__ = (
        UniqueConstraint("label", "oid", name="uq_scan_oids_label_oid"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    label: Mapped[str] = mapped_column(String(96))
    oid: Mapped[str] = mapped_column(String(191))
    description: Mapped[str | None] = mapped_column(Text)
    vendor: Mapped[str | None] = mapped_column(String(96))     # opsional, substring match
    model: Mapped[str | None] = mapped_column(String(96))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at = _now()


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        Index(f"ix_{SCHEMA}_scan_runs_started", "started_at"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.scan_groups.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|done|failed|cancelled
    started_at = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hosts_total: Mapped[int] = mapped_column(Integer, default=0)
    hosts_done: Mapped[int] = mapped_column(Integer, default=0)
    hosts_found: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class ScanResult(Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        UniqueConstraint("run_id", "ip", name="uq_scan_results_run_ip"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.scan_runs.id", ondelete="CASCADE"), index=True)
    ip: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|timeout|error
    sys_object_id: Mapped[str | None] = mapped_column(String(191))
    sys_name: Mapped[str | None] = mapped_column(String(191))
    sys_descr: Mapped[str | None] = mapped_column(Text)
    vendor: Mapped[str | None] = mapped_column(String(96))
    model: Mapped[str | None] = mapped_column(String(128))
    serial: Mapped[str | None] = mapped_column(String(128))
    uptime_s: Mapped[int | None] = mapped_column(Integer)
    if_count: Mapped[int | None] = mapped_column(Integer)
    fdb_count: Mapped[int | None] = mapped_column(Integer)  # baris port map dari bridge FDB
    oid_values: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(255))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK, index=True)
    created_at = _now()


class EndpointPortMapping(Base):
    """MAC ↔ port switch dari BRIDGE-MIB (dot1d) / Q-BRIDGE-MIB (dot1q).

    Satu baris = satu MAC yang dipelajari di satu port switch. MAC yang hilang tidak
    dihapus: `present=false` (delta, pola sama dengan hw_components).
    """
    __tablename__ = "endpoint_port_mappings"
    __table_args__ = (
        UniqueConstraint("switch_asset_id", "vlan", "mac",
                         name="uq_endpoint_port_switch_vlan_mac"),
        Index(f"ix_{SCHEMA}_epm_mac", "mac"),
        Index(f"ix_{SCHEMA}_epm_switch", "switch_asset_id"),
        Index(f"ix_{SCHEMA}_epm_endpoint", "endpoint_asset_id"),
        {"schema": SCHEMA},
    )

    id = _uuid_pk()
    switch_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.assets.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.scan_runs.id", ondelete="SET NULL"))
    vlan: Mapped[int] = mapped_column(Integer, default=0)  # 0 = tidak diketahui (dot1d)
    mac: Mapped[str] = mapped_column(String(32))
    bridge_port: Mapped[int | None] = mapped_column(Integer)
    if_index: Mapped[int | None] = mapped_column(Integer)
    if_name: Mapped[str | None] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), default="learned")
    endpoint_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen = _now()
    last_seen = _now()
