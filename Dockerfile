FROM docker.m.daocloud.io/library/python:3.11-slim AS base

WORKDIR /app

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PYPI_HOST=pypi.tuna.tsinghua.edu.cn

RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g; s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i ${PYPI_INDEX} --trusted-host ${PYPI_HOST} -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY monitoring ./monitoring
COPY alembic ./alembic
COPY data ./data
RUN mkdir -p /app/data /app/models \
    /app/storage/projects \
    /app/storage/ltx_downloads \
    /app/storage/final_videos \
    /app/storage/video_production \
    /app/storage/director_runs \
    /app/storage/director_evolution \
    && groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
