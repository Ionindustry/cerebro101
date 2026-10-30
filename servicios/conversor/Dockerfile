# Servicio de conversión de documentos (.doc, .odt, .rtf → .docx) con LibreOffice, aparte de la API. Contexto de construcción: la RAÍZ del repositorio.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 conversor
WORKDIR /app
COPY servicios/conversor/app.py ./app.py
COPY api/cerebro/licitaciones/conversion_local.py ./conversion_local.py
USER conversor
EXPOSE 8080
CMD ["python", "app.py"]
