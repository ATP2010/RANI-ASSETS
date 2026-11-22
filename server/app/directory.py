"""Active Directory (LDAP/LDAPS) — read-only. Dipakai F5.4 (connector), F5.5 (sync),
F5.6 (login). Tidak ada operasi tulis ke AD sama sekali.

Konvensi keamanan:
- Bind password disimpan terenkripsi Fernet (app.crypto), tidak pernah keluar API/UI.
- Password user saat login hanya dipakai untuk bind sekali (tidak disimpan).
- Filter LDAP selalu di-escape (ldap3 escape_filter_chars) — anti injection.
- Operasi LDAP sinkron: panggil lewat run_in_threadpool dari handler async.
"""
import logging
import re
import time
import uuid
from urllib.parse import urlsplit

import ldap3
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.config import get_settings
from app.crypto import decrypt_directory_secret, encrypt_directory_secret

log = logging.getLogger("rani.directory")
settings = get_settings()

DEFAULT_USER_FILTER = ("(&(objectCategory=person)(objectClass=user)"
                       "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))")
UAC_DISABLED = 0x2
MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"

# Atribut opsional yang HANYA diminta bila ada di skema server (AD: semua ada;
# OpenLDAP lab: objectGUID/userAccountControl/dll tidak ada).
_OPTIONAL_ATTRS = ("objectGUID", "displayName", "mail", "userPrincipalName",
                   "userAccountControl", "memberOf")

_schema_cache: dict = {}
_ATTR_NAME_RE = re.compile(r"\bNAME\s+'([^']+)'")


def _schema_attr_names(connector) -> set[str]:
    """Set atribut (lowercase) di skema server; cache 5 menit per connector."""
    key = (getattr(connector, "id", None) or connector.url,
           connector.url, connector.bind_dn, connector.base_dn)
    now = time.time()
    hit = _schema_cache.get(key)
    if hit and now - hit[0] < 300:
        return hit[1]
    names: set[str] = set()
    try:
        with _connection(connector) as conn:
            conn.search("cn=subschema", "(objectClass=subschema)",
                        search_scope=ldap3.BASE,
                        attributes=["attributeTypes"])
            blob = []
            for entry in conn.entries:
                blob.extend(str(v) for v in entry.entry_attributes_as_dict.get("attributeTypes", []))
            names = {m.group(1).lower() for m in _ATTR_NAME_RE.finditer(" ".join(blob))}
    except Exception as exc:  # noqa: BLE001 — deteksi gagal: fallback minimal
        log.info("schema detection gagal untuk %s: %s", getattr(connector, "name", "?"), exc)
        names = {"cn", "memberof"}
    _schema_cache[key] = (now, names)
    return names


def _user_attrs(connector) -> list[str]:
    schema = _schema_attr_names(connector)
    attrs = ["cn", "sAMAccountName"] if "samaccountname" in schema else ["cn"]
    for attr in _OPTIONAL_ATTRS:
        if attr.lower() in schema:
            attrs.append(attr)
    return attrs if len(attrs) > 1 else ["cn"]


class DirectoryError(Exception):
    pass


def default_user_filter() -> str:
    return DEFAULT_USER_FILTER


def encrypt_bind_password(plain: str) -> str:
    return encrypt_directory_secret(plain, settings.RANI_INGEST_PEPPER)


def decrypt_bind_password(enc: str | None) -> str:
    if not enc:
        raise DirectoryError("bind password connector belum diisi")
    return decrypt_directory_secret(enc, settings.RANI_INGEST_PEPPER)


def _server(connector, *, timeout: float = 6.0) -> ldap3.Server:
    parts = urlsplit(connector.url or "")
    host = (parts.hostname or "").strip()
    if not host:
        raise DirectoryError("URL connector tidak valid (mis. ldaps://dc01.corp.local:636)")
    port = parts.port or (636 if connector.use_ldaps else 389)
    use_ssl = bool(connector.use_ldaps) or parts.scheme == "ldaps"
    tls = None
    if use_ssl:
        import ssl as ssl_module
        tls = ldap3.Tls(validate=ssl_module.CERT_REQUIRED if connector.tls_verify
                        else ssl_module.CERT_NONE,
                        ca_certs_file=_ca_file(connector.ca_cert_pem) if connector.ca_cert_pem else None,
                        version=__import__("ssl").PROTOCOL_TLS_CLIENT)
    return ldap3.Server(host, port=port, use_ssl=use_ssl, tls=tls,
                        connect_timeout=timeout)


_ca_tmp: dict[str, str] = {}


def _ca_file(pem: str) -> str:
    """ldap3 butuh path file CA; tulis ke tmp terproteksi (idempotent per isi)."""
    import hashlib
    import tempfile

    digest = hashlib.sha256(pem.encode()).hexdigest()
    path = _ca_tmp.get(digest)
    if path is None:
        with tempfile.NamedTemporaryFile("w", suffix=".pem", prefix="rani-ca-",
                                         delete=False) as fh:
            fh.write(pem)
            path = fh.name
        _ca_tmp[digest] = path
    return path


def _connection(connector, user: str | None = None, password: str | None = None,
                *, receive_timeout: int = 10) -> ldap3.Connection:
    server = _server(connector)
    conn = ldap3.Connection(server, user=user or connector.bind_dn,
                            password=password if password is not None
                            else decrypt_bind_password(connector.bind_password_enc),
                            auto_bind=True, read_only=True, receive_timeout=int(receive_timeout))
    return conn


def test_connection(connector) -> dict:
    """Bind service + baca rootDSE + hitung user/grup. Tidak membocorkan password."""
    try:
        with _connection(connector) as conn:
            conn.search("", "(objectClass=*)", attributes=None,
                        search_scope=ldap3.BASE)
            users = _count(conn, connector.base_dn, connector.user_filter)
            groups = _count(conn, connector.base_dn, connector.group_filter)
            return {"ok": True, "users": users, "groups": groups, "error": None}
    except DirectoryError as exc:
        return {"ok": False, "users": None, "groups": None, "error": str(exc)}
    except LDAPException as exc:
        return {"ok": False, "users": None, "groups": None,
                "error": _friendly_ldap_error(exc)}


def _count(conn, base_dn: str, ldap_filter: str) -> int:
    """Hitung entri (1.2.840.113556.1.4.970 paged search dengan page=1 untuk jumlah)."""
    total = 0
    try:
        for entry in conn.extend.standard.paged_search(
                base_dn, ldap_filter, paged_size=200, time_limit=20,
                attributes=[], generator=True):
            if entry.get("dn"):
                total += 1
            if total > 50000:
                return total
    except LDAPException as exc:
        raise DirectoryError(_friendly_ldap_error(exc)) from exc
    return total


def browse_groups(connector, query: str | None = None, limit: int = 100) -> list[dict]:
    filt = connector.group_filter or "(objectClass=group)"
    if query:
        q = escape_filter_chars(query.strip())
        filt = f"(&{filt}(|(cn=*{q}*)(name=*{q}*)))"
    out: list[dict] = []
    with _connection(connector) as conn:
        conn.search(connector.base_dn, filt,
                    attributes=["cn", "sAMAccountName"],
                    size_limit=limit)
        for entry in conn.entries:
            dn = entry.entry_dn
            out.append({"dn": dn,
                        "name": _attr(entry, "cn") or _attr(entry, "sAMAccountName")
                        or dn})
    out.sort(key=lambda g: (g["name"] or "").lower())
    return out


def _first(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _attr(entry, name: str):
    try:
        value = entry[name].value
    except Exception:
        return None
    return value


def _guid_str(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.lower()
    try:
        return str(uuid.UUID(bytes_le=bytes(raw)))
    except Exception:
        try:
            return uuid.UUID(bytes=bytes(raw)).hex
        except Exception:
            return None


def _uac(entry) -> int:
    raw = _attr(entry, "userAccountControl")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def search_group_members(connector, group_dn: str) -> list[dict]:
    """Semua user anggota group (nested bila nested_groups aktif)."""
    member = escape_filter_chars(group_dn)
    if connector.nested_groups:
        rule = f"memberOf:{MATCHING_RULE_IN_CHAIN}"
        filt = f"({rule}={member})"
    else:
        filt = f"(memberOf={member})"
    inner = connector.user_filter or DEFAULT_USER_FILTER
    search_filter = f"(&{filt}{inner})"
    members: list[dict] = []
    with _connection(connector) as conn:
        for item in conn.extend.standard.paged_search(
                connector.base_dn, search_filter, paged_size=500, time_limit=60,
                attributes=_user_attrs(connector), generator=True):
            if not item.get("dn") or item.get("type") == "searchResRef":
                continue
            attrs = item.get("attributes", {})
            attrs = {k: _first(v) for k, v in attrs.items()}
            members.append({
                "dn": item["dn"],
                "cn": _first(attrs.get("cn")),
                "sam": str(_first(attrs.get("sAMAccountName")) or "").lower() or None,
                "guid": _guid_str(_first(attrs.get("objectGUID"))),
                "display_name": _first(attrs.get("displayName")) or _first(attrs.get("cn")),
                "email": _first(attrs.get("mail")),
                "upn": _first(attrs.get("userPrincipalName")),
                "uac": int(attrs.get("userAccountControl") or 0),
            })
    return members


def find_user(connector, sam: str) -> dict | None:
    sam_escaped = escape_filter_chars(sam.lower())
    filt = f"(&(sAMAccountName={sam_escaped}){connector.user_filter or DEFAULT_USER_FILTER})"
    with _connection(connector) as conn:
        conn.search(connector.base_dn, filt, attributes=_user_attrs(connector))
        for entry in conn.entries:
            return {
                "dn": entry.entry_dn,
                "cn": _attr(entry, "cn"),
                "sam": (_attr(entry, "sAMAccountName") or "").lower(),
                "guid": _guid_str(_attr(entry, "objectGUID")) if _attr(entry, "objectGUID") is not None else None,
                "display_name": _attr(entry, "displayName") or _attr(entry, "cn"),
                "email": _attr(entry, "mail"),
                "upn": _attr(entry, "userPrincipalName"),
                "uac": _uac(entry),
                "member_of": list(_attr(entry, "memberOf") or []),
            }
    return None


def bind_as_user(connector, user_dn: str, password: str) -> bool:
    """Bind sebagai user untuk memverifikasi password. Tidak menyimpan apa pun."""
    try:
        with _connection(connector, user=user_dn, password=password):
            return True
    except LDAPException:
        return False


def dn_key(dn: str | None) -> str:
    """Kunci DN untuk perbandingan (case-insensitive, abaikan spasi setelah koma)."""
    if not dn:
        return ""
    return ",".join(part.strip() for part in str(dn).split(",")).lower()


def group_dns_for_user(connector, user_dn: str) -> list[str]:
    """Semua DN group (nested bila nested_groups aktif) yang berisi user. Return lowercase."""
    out: list[str] = []
    if connector.nested_groups:
        user_escaped = escape_filter_chars(user_dn)
        filt = f"(&(objectClass=group)(member:{MATCHING_RULE_IN_CHAIN}={user_escaped}))"
        with _connection(connector) as conn:
            for item in conn.extend.standard.paged_search(
                    connector.base_dn, filt, paged_size=500, time_limit=30,
                    attributes=[], generator=True):
                dn = item.get("dn")
                if dn:
                    out.append(str(dn).lower())
        return out
    filt_user = "(objectClass=*)"
    with _connection(connector) as conn:
        conn.search(user_dn, filt_user, search_scope=ldap3.BASE, attributes=["memberOf"])
        for entry in conn.entries:
            values = entry.entry_attributes_as_dict.get("memberOf", [])
            if isinstance(values, str):
                values = [values]
            for dn in values:
                out.append(str(dn).lower())
    return out


def user_enabled(uac: int) -> bool:
    return not bool(uac & UAC_DISABLED)


def _friendly_ldap_error(exc: LDAPException) -> str:
    text = str(exc).strip()
    for needle, message in (
        ("invalidCredentials", "kredensial bind ditolak (invalid credentials)"),
        ("invalid credentials", "kredensial bind ditolak (invalid credentials)"),
        ("unable to open socket", "tidak bisa terhubung ke server LDAP/LDAPS (host/port/firewall)"),
        ("certificate verify failed", "verifikasi sertifikat TLS gagal (CA belum diunggah/dipercaya)"),
        ("strongerAuthRequired", "server menuntut LDAPS/StartTLS — aktifkan LDAPS"),
        ("No such object", "base DN tidak ditemukan"),
        ("timed out", "timeout menghubungi server LDAP"),
        ("socket ssl wrapping error", "gagal handshake TLS (port/pengaturan LDAPS salah?)"),
    ):
        if needle.lower() in text.lower():
            return message
    return f"error LDAP: {text[:200]}"


def parse_login_username(raw: str) -> dict | None:
    """Routing login: {'kind': 'local'|'ad', ...}. Username polos selalu lokal."""
    value = (raw or "").strip()
    if not value:
        return None
    if "\\" in value:
        domain, _, sam = value.partition("\\")
        if not domain.strip() or not sam.strip():
            return None
        return {"kind": "ad", "match": "netbios",
                "domain": domain.strip().lower(), "sam": sam.strip().lower(),
                "upn": None, "raw": value}
    if "@" in value:
        sam, _, fqdn = value.partition("@")
        if not sam.strip() or not fqdn.strip():
            return None
        return {"kind": "ad", "match": "fqdn",
                "domain": fqdn.strip().lower(), "sam": sam.strip().lower(),
                "upn": value.lower(), "raw": value}
    return {"kind": "local", "sam": value.lower(), "raw": value}
