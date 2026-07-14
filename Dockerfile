FROM python:3.14-slim

# tesseract-ocr + tesseract-ocr-ita: OCR per i PDF scansionati (fallback, §9 del piano).
# ghostscript + unpaper + poppler-utils: dipendenze di ocrmypdf per normalizzare/pulire i PDF prima dell'OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ita \
    ghostscript \
    unpaper \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Binario uv ufficiale (nessuna chiamata di rete extra in build): installa le
# dipendenze dalle versioni esatte risolte in uv.lock, non dai range aperti
# (">=") di pyproject.toml, per una build riproducibile nel tempo.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

# Le dipendenze (pesanti: pymupdf, ocrmypdf) vanno installate PRIMA di copiare il
# codice applicativo: una modifica in packages/payroll-ingest/src/ non invalida
# piu' questo layer. Workspace uv: root virtuale + due membri, ma solo
# payroll-ingest gira nel container (payroll-cli e' un tool host, mai installato
# qui) — entrambi i pyproject.toml servono comunque per la discovery del
# workspace, coerente con uv.lock che li conosce entrambi.
COPY pyproject.toml uv.lock ./
COPY packages/payroll-ingest/pyproject.toml packages/payroll-ingest/pyproject.toml
COPY packages/payroll-cli/pyproject.toml packages/payroll-cli/pyproject.toml
RUN uv sync --frozen --no-install-workspace

COPY packages/payroll-ingest/src packages/payroll-ingest/src
COPY packages/payroll-ingest/alembic.ini ./
COPY packages/payroll-ingest/alembic ./alembic
COPY scripts ./scripts
RUN uv sync --frozen --package payroll-ingest

# UID/GID 1000 = primo utente standard su Debian/Ubuntu: evita che i file creati
# nelle cartelle montate dall'host (input/processed/error/logs/export) finiscano
# di proprieta' di root. Sovrascrivibile in build se l'utente host ha UID diverso.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g "${APP_GID}" app && useradd -m -u "${APP_UID}" -g "${APP_GID}" app \
    && chown -R app:app /app
USER app

ENV PAYROLL_BASE_DIR=/data
VOLUME ["/data"]

CMD ["payroll-ingest", "--help"]
