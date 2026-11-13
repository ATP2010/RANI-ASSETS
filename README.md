# RANI ProjectDev
IT asset inventory self-hosted (mirip Lansweeper): **raniPush** agent → FastAPI ingest → dashboard AdminLTE realtime (WebSocket).

- Requirements & analisis: [`../baseOn/analysis results.md`](../baseOn/analysis%20results.md)
- Doktrin untuk AI agent/dev: [`DEVGUIDE.md`](DEVGUIDE.md) ← **baca dulu**
- Progres: [`CHECKLIST.md`](CHECKLIST.md)

## Quick start
```bash
cp .env.example .env   # isi password
docker compose up -d
# UI: http://192.168.88.92:8091   (login default ada di log boot saat seed admin)
```

## Deploy image ke registry lokal (buat migrasi)
```bash
bash scripts/push-registry.sh          # build + push → 192.168.88.92:5000/rani-{api,worker}
# di server baru:
git clone <repo> && cd ProjectDev && docker compose pull && docker compose up -d
```

## raniPush (Windows)
```
raniPush 192.168.88.92                 # collect + push
schtasks /create /tn RaniPush /sc hourly /tr "C:\Rani\raniPush.exe 192.168.88.92"
```
