FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.lock \
    && groupadd --gid 10001 nexo \
    && useradd --uid 10001 --gid nexo --no-create-home --shell /usr/sbin/nologin nexo \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
ENV NEXO_DATA_DIR=/data
COPY src/ ./src/
COPY web/ ./web/
COPY alembic.ini ./
COPY migrations/ ./migrations/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import json, urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3); assert r.status == 200 and json.load(r) == {'status':'ok','service':'nexo-home'}"
CMD ["python", "-m", "nexo.cli", "serve"]
