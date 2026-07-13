FROM python:3.12-slim

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
# codice applicativo: una modifica in src/ non invalida piu' questo layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
RUN uv sync --frozen

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
