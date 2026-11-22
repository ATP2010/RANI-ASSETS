FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Jakarta

LABEL org.opencontainers.image.title="RANI — Resource & Asset Network Intelligence" \
      org.opencontainers.image.description="IT asset inventory self-hosted: raniPush agent, dashboard realtime, custom reports SQL, SNMP scan + custom OID." \
      org.opencontainers.image.licenses="Proprietary" \
      org.opencontainers.image.vendor="Adhitya TP"

WORKDIR /srv

# tzdata supaya TZ=Asia/Jakarta benar-benar dipakai container
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

COPY alembic.ini /srv/alembic.ini
COPY db /srv/db
COPY server/app /srv/app
COPY server/worker /srv/worker
COPY server/tests /srv/tests
COPY actions /srv/actions
COPY schema /srv/schema
COPY docs /srv/docs
# Artefak agent + skrip unduhan ikut di image supaya deployment "pull & run"
# tidak butuh bind mount. Saat dev, compose mount ./release dan ./scripts
# menimpa direktori ini.
COPY docker/artifacts/ /srv/release/
COPY scripts/ /srv/scripts/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]