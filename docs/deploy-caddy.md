# Deploy RANI dengan Caddy (HTTPS otomatis)

Modul opsional: reverse proxy + TLS otomatis (Let's Encrypt) di depan RANI.
Tanpa modul ini RANI tetap jalan di port `RANI_HTTP_PORT` (default 8091) via HTTP.

## Prasyarat
- Domain publik (mis. `rani.example.com`) dengan DNS A/AAAA → IP server.
- Port 80 dan 443 terbuka di firewall:
  ```bash
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  ```
- `.env` berisi:
  ```
  RANI_DOMAIN=rani.example.com
  RANI_ACME_EMAIL=admin@example.com
  ```

## Jalankan
```bash
# dari folder instalasi (default /opt/rani)
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml up -d

# cek
docker compose -f docker-compose.hub.yml -f docker-compose.caddy.yml ps
curl -sS https://rani.example.com/health
```

Caddy otomatis:
- meminta & memperbarui sertifikat Let's Encrypt,
- redirect HTTP → HTTPS,
- reverse proxy ke `api:8000` (termasuk WebSocket realtime),
- menambah security headers (HSTS, nosniff, dll.).

## Mode tanpa Caddy (LAN / dev)
Jalankan hanya file utama:
```bash
docker compose -f docker-compose.hub.yml up -d
# akses http://<ip>:8091
```

## Catatan keamanan (produksi)
- Batasi akses langsung ke port 8091: set `RANI_HTTP_PORT=127.0.0.1:8091` di `.env`
  (Caddy tetap akses via network internal), atau hapus `ports:` api di compose override.
- Untuk SaaS multi-tenant, ganti `{$RANI_DOMAIN:localhost}` di `Caddyfile` dengan
  wildcard `*.rani.app` + DNS challenge (mis. Cloudflare) agar setiap tenant dapat
  subdomain + sertifikat otomatis.
- Rate limiting tidak tersedia di Caddy core; andalkan `RANI_LOGIN_MAX_ATTEMPTS`
  di aplikasi, atau build image Caddy custom dengan plugin `caddy-ratelimit`.

## Troubleshooting
- Cert gagal terbit: cek DNS A record sudah propagasi (`dig rani.example.com`), dan
  port 80 terbuka (Let's Encrypt butuh HTTP-01 challenge).
- WebSocket tidak realtime: pastikan `flush_interval -1` ada di Caddyfile (sudah default).
- Lihat log Caddy: `docker compose ... logs -f caddy`.
- Validasi Caddyfile: `docker run --rm -v $PWD/Caddyfile:/etc/caddy/Caddyfile:ro caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile`
