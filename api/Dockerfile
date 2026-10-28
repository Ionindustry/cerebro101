FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/api

# El orden de las capas importa: lo que casi nunca cambia va primero y lo que cambia a diario, al final. Así un cambio de código reconstruye en
# segundos solo las dos últimas capas y no reinstala Tesseract, las dependencias de Python ni el navegador (antes: 5-8 minutos y muchos GB
# escritos en cada actualización, que es donde Docker se quejaba de capas corruptas en equipos inestables).

# 1. Sistema. OCR (facturas escaneadas, fotos de documentos): Tesseract en español, catalán e inglés y Poppler para convertir PDF a imagen.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-cat tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 2. Dependencias de Python. Solo dependen de pyproject.toml: se instalan con un paquete vacío (`cerebro`) que se quita enseguida, y se vuelve a
#    instalar el de verdad en el paso 4. Esta capa solo se rehace si cambia pyproject.toml.
COPY api/pyproject.toml ./
RUN mkdir -p cerebro && touch cerebro/__init__.py \
    && pip install --no-cache-dir ".[investigacion,observabilidad]" \
    && pip uninstall -y cerebro-101 \
    && rm -rf cerebro build ./*.egg-info

# 3. Navegador opcional (investigación web): si falla no debe impedir la construcción. Depende de la capa anterior, no del código.
RUN playwright install --with-deps chromium || true

# 4. El código. `--no-deps`: las dependencias ya están; esto solo instala el paquete (segundos).
COPY api/cerebro ./cerebro
RUN pip install --no-cache-dir --no-deps .

# 5. Configuración, scripts, esquema y pruebas (lo que más cambia).
COPY config /app/config
COPY scripts /app/scripts
COPY db /app/db
COPY api/tests ./tests
ENV CEREBRO_CONFIG=/app/config
EXPOSE 8000
CMD ["uvicorn", "cerebro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
