FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/api
COPY api/pyproject.toml ./
COPY api/cerebro ./cerebro
# OCR (facturas escaneadas, fotos de documentos): Tesseract en español, catalán e inglés y Poppler para convertir PDF a imagen
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-cat tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir ".[investigacion,observabilidad]"
# Navegador opcional (investigación web): si falla no debe impedir la construcción
RUN playwright install --with-deps chromium || true
COPY config /app/config
COPY scripts /app/scripts
COPY db /app/db
COPY api/tests ./tests
ENV CEREBRO_CONFIG=/app/config
# la versión del código (la pone la integración continua): se muestra en /salud y en el panel; va al final para no invalidar la caché de las capas pesadas
ARG CODIGO_VERSION=desconocida
ENV CODIGO_VERSION=$CODIGO_VERSION
EXPOSE 8000
CMD ["uvicorn", "cerebro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
