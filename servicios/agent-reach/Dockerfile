FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" yt-dlp \
    https://github.com/Panniantong/agent-reach/archive/main.zip
# Modo seguro: solo comprueba el entorno, no instala paquetes del sistema.
RUN agent-reach install --env=auto --safe || true
WORKDIR /app
COPY servidor.py .
EXPOSE 8090
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8090"]
