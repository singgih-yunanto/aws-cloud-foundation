# Image lab-app untuk Hari 3 (ECS Fargate dan ECS EC2).
# Tiga tag dibangun dari kode yang sama (lihat build-and-push.sh): v1, v2, dan v-bad.
# Perbedaannya hanya label versi dan START_UNHEALTHY (v-bad gagal health check, untuk latihan rollback).
FROM python:3.12-slim

ARG APP_VERSION=v1
ARG START_UNHEALTHY=no

# Port 8080 agar tidak perlu root. LOG_FILE=/dev/stdout agar awslogs menangkap log JSON.
# DB_MODE=mock: tanpa DocumentDB. TRACING=off: dinyalakan lewat task definition pada Lab 9.
ENV PORT=8080 \
    LOG_FILE=/dev/stdout \
    DB_MODE=mock \
    TRACING=off \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    START_UNHEALTHY=${START_UNHEALTHY}

WORKDIR /app
COPY requirements-otel.txt .
RUN pip install --no-cache-dir -r requirements-otel.txt
COPY lab-app.py .

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8080
CMD ["python", "lab-app.py"]
