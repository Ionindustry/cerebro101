FROM python:3.12-slim
# faster-whisper abre el audio con PyAV («av»): con un «av» antiguo falla con «open() got an unexpected keyword argument 'metadata_errors'».
# Los mínimos fuerzan una instalación nueva aunque Docker conserve en caché una anterior.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart "faster-whisper>=1.2" "av>=14" piper-tts
WORKDIR /app
COPY servidor.py .
# Descarga las voces de Piper (https://huggingface.co/rhasspy/piper-voices) en ./voces
VOLUME /voces
EXPOSE 8100
CMD ["uvicorn", "servidor:app", "--host", "0.0.0.0", "--port", "8100"]
