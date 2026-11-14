#!/usr/bin/env python3
"""Smoke test end-to-end RANI (tanpa browser, butuh stack sudah jalan).

Alur: login admin → buat enrollment token → enroll agent (agent/raniPush.py) →
push → tunggu worker → cek API/DB via HTTP. Exit code 0 = semua lulus.

Pakai:
    python3 scripts/smoke_test.py [--base http://127.0.0.1:8091] [--keep]
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not condition:
        FAILED.append(name)


def load_env() -> dict:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("RANI_", "POSTGRES_"))})
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8091")
    parser.add_argument("--keep", action="store_true", help="jangan revoke agent uji di akhir")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    env = load_env()

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # 1. health
    health = json.loads(opener.open(base + "/health").read())
    check("health db ok", health.get("db") is True, str(health))

    # 2. login
    opener.open(urllib.request.Request(
        base + "/login", method="POST",
        data=urllib.parse.urlencode({"username": env.get("RANI_ADMIN_USER", "admin"),
                                     "password": env.get("RANI_ADMIN_PASSWORD", ""),
                                     "next": "/"}).encode()))
    check("login admin", any(c.name == "rani_session" for c in jar))

    # 3. buat token enrollment
    resp = opener.open(urllib.request.Request(
        base + "/agents/tokens", method="POST",
        data=urllib.parse.urlencode({"label": "smoke-test", "ttl_hours": "1"}).encode()))
    token = urllib.parse.parse_qs(urllib.parse.urlparse(resp.url).query).get("token", [""])[0]
    check("enrollment token dibuat", bool(token))

    # 4. enroll agent memakai CLI asli
    enroll = subprocess.run([sys.executable, str(ROOT / "agent" / "raniPush.py"),
                             "--enroll", token, base], capture_output=True, text=True)
    check("agent enroll (CLI)", enroll.returncode == 0, enroll.stdout.strip() or enroll.stderr.strip())

    # 5. push payload hasil koleksi nyata (mode legacy HMAC, sudah enroll)
    push = subprocess.run([sys.executable, str(ROOT / "agent" / "raniPush.py"), base],
                          capture_output=True, text=True)
    check("agent push (CLI)", push.returncode == 0, push.stdout.strip() or push.stderr.strip())

    # 5b. push tanpa token dari config kosong (alur default agent 0.2+)
    with tempfile.TemporaryDirectory() as clean_dir:
        push_free = subprocess.run([sys.executable, str(ROOT / "agent" / "raniPush.py"), base],
                                   capture_output=True, text=True,
                                   env=dict(os.environ, RANI_CONFIG_DIR=clean_dir))
    check("agent push tanpa token (CLI)", push_free.returncode == 0 and "push ok" in push_free.stdout,
          (push_free.stdout or push_free.stderr).strip()[-160:])

    # 6. worker memproses → asset muncul
    item = None
    for _ in range(15):
        time.sleep(1)
        data = json.loads(opener.open(base + "/api/v1/assets?per_page=50").read())
        hits = [i for i in data["items"] if i["hostname"]]
        if hits:
            item = hits[0]
        if item and item["software_count"]:
            break
    check("asset ter-reconcile", item is not None, json.dumps(item)[:160] if item else "")
    if item:
        check("software terhitung", item["software_count"] > 0, f"{item['software_count']} paket")

    # 7. halaman UI utama
    for path, marker in (("/", "Dashboard"), ("/assets", "Assets"),
                         ("/agents", "Download agent")):
        body = opener.open(base + path).read().decode("utf-8", "replace")
        check(f"UI {path} render", marker in body, f"{len(body)} bytes")

    # 7b. unduhan artefak agent dari browser (login reader/admin)
    for name in ("raniPush-signed.exe", "rani-push-signing.cer", "install-cert.ps1"):
        resp = opener.open(base + "/downloads/" + name)
        blob = resp.read()
        check(f"download {name}", resp.status == 200 and len(blob) > 100,
              f"{len(blob)} bytes")

    # 7c. custom reports: list, run contoh, guard SQL, export CSV
    body = opener.open(base + "/reports").read().decode("utf-8", "replace")
    check("UI /reports render", "Custom reports" in body, f"{len(body)} bytes")
    hrefs = [h for h in body.split('href="/reports/') if h[:36].replace("-", "").isalnum()]
    if hrefs:
        rid = hrefs[0][:36]
        req = urllib.request.Request(base + f"/api/v1/reports/{rid}/run", method="POST",
                                     headers={"Accept": "application/json"})
        payload = json.loads(opener.open(req).read())
        check("report run (contoh)", isinstance(payload.get("columns"), list),
              f"{payload.get('row_count')} baris · {payload.get('duration_ms')} ms")
        csv_rep = opener.open(base + f"/reports/{rid}/export.csv")
        check("report export CSV", csv_rep.status == 200 and
              csv_rep.headers.get("content-type", "").startswith("text/csv"),
              f"{len(csv_rep.read())} bytes")
    guarded = opener.open(urllib.request.Request(
        base + "/reports/new", method="POST",
        data=urllib.parse.urlencode({"name": "smoke-guard",
                                     "description": "guard",
                                     "sql_text": "DELETE FROM assets",
                                     "action": "save"}).encode())).read().decode("utf-8", "replace")
    check("report guard menolak DML", "hanya query SELECT" in guarded)

    # 8. stats + CSV
    stats = json.loads(opener.open(base + "/api/v1/stats").read())
    check("stats aset > 0", stats["assets_total"] > 0, str(stats["assets_total"]))
    csv_body = opener.open(base + "/export/assets.csv").read().decode()
    check("export CSV berisi header", csv_body.startswith("hostname,ip,os"), csv_body.splitlines()[0][:60])

    # 9. endpoint terproteksi menolak tanpa sesi
    anon = urllib.request.build_opener()
    try:
        anon.open(base + "/api/v1/assets")
        check("API menolak tanpa sesi", False)
    except urllib.error.HTTPError as exc:
        check("API menolak tanpa sesi", exc.code == 401, str(exc.code))

    print()
    if FAILED:
        print(f"GAGAL: {len(FAILED)} cek → {', '.join(FAILED)}")
        return 1
    print("SEMUA CEK LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())