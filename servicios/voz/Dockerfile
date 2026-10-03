FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart faster-whisper piper-tts
WORKDIR /app
COPY servidor.py .
# Descarga las voces de Piper (https://huggingface.co/rhasspy/piper-voices) en ./voces
VOLUME /voces
EXPOSE 8100
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8100"]
