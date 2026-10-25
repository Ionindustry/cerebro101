FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" "pyyaml>=6.0"
COPY servidor.py ./
EXPOSE 8080
USER nobody
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8080"]
