FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/api
COPY api/pyproject.toml ./
COPY api/cerebro ./cerebro
RUN pip install --no-cache-dir ".[investigacion,observabilidad]"
# Navegador opcional (investigación web): si falla no debe impedir la construcción
RUN playwright install --with-deps chromium || true
COPY config /app/config
COPY scripts /app/scripts
COPY api/tests ./tests
ENV CEREBRO_CONFIG=/app/config
EXPOSE 8000
CMD ["uvicorn", "cerebro.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
