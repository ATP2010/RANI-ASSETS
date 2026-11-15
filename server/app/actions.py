"""Actions asset gaya Lansweeper ("Create and run actions").

Tiap action adalah hyperlink dengan parameter dari field asset — dieksekusi
**di mesin klien** (bukan di server): browser membuka URL/protokol handler
(`rdp://`, `ssh://`, `file://`, `vnc://`) atau halaman web biasa. Copy action
menyalin teks (mis. `mstsc /v:<ip>`) ke clipboard klien.

Referensi parameter (Lansweeper): {ipaddress}, {assetname}, {fqdn}, {dnsname},
{domain}, {mac}, {tag}. Tambahan: {hostname} alias {assetname}.
"""

ACTION_LINKS: list[tuple[str, str, str]] = [
    # key, label, template URL
    ("http", "Buka di browser (HTTP)", "http://{ipaddress}"),
    ("https", "Buka di browser (HTTPS)", "https://{ipaddress}"),
    ("share", "Buka berbagi file (C$)", "file:///{ipaddress}/c$"),
    ("rdp", "Remote Desktop (RDP)", "rdp://{ipaddress}"),
    ("ssh", "SSH", "ssh://{ipaddress}"),
    ("vnc", "VNC", "vnc://{ipaddress}"),
]

ACTION_COPIES: list[tuple[str, str, str]] = [
    ("mstsc", "Salin `mstsc` untuk RDP", "mstsc /v:{ipaddress}"),
    ("ip", "Salin alamat IP", "{ipaddress}"),
    ("mac", "Salin MAC", "{mac}"),
    ("hostname", "Salin hostname", "{hostname}"),
]


def _fqdn(asset) -> str:
    host = (getattr(asset, "hostname", "") or "").strip()
    if "." in host:
        return host
    domain = (getattr(asset, "domain", "") or "").strip().lower()
    if host and domain and domain not in ("workgroup", "localhost"):
        return f"{host}.{domain}"
    return host


def asset_actions(asset) -> list[dict]:
    ip = (getattr(asset, "ip_last", "") or "").strip()
    host = (getattr(asset, "hostname", "") or "").strip()
    params = {
        "ipaddress": ip,
        "assetname": host,
        "hostname": host,
        "fqdn": _fqdn(asset),
        "dnsname": _fqdn(asset),
        "domain": (getattr(asset, "domain", "") or "").strip(),
        "mac": (getattr(asset, "primary_mac", "") or "").strip(),
        "tag": (getattr(asset, "serial", "") or "").strip(),
    }
    items: list[dict] = []
    if ip:
        for key, label, template in ACTION_LINKS:
            items.append({"key": key, "label": label,
                          "href": template.format(**params)})
    for key, label, template in ACTION_COPIES:
        if "{ipaddress}" in template and not ip:
            continue
        text = template.format(**params).strip()
        if text:
            items.append({"key": key, "label": label, "copy": text})
    return items
