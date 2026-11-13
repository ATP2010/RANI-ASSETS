FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Jakarta

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
COPY schema /srv/schema

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]