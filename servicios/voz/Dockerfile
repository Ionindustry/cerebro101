FROM python:3.12-slim
# faster-whisper 1.2 abre el audio con PyAV («av») usando un argumento (`metadata_errors`) que `av` 19 ya no admite: con la última versión de `av`
# cada transcripción falla con «open() got an unexpected keyword argument 'metadata_errors'». Se limita a la serie 14–18, que sí funciona.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart "faster-whisper>=1.2,<1.3" "av>=14,<19" piper-tts
# Para usar la tarjeta gráfica NVIDIA: cuBLAS 12 y cuDNN 9, que CTranslate2 necesita y la imagen base no trae (arranque.sh las pone en LD_LIBRARY_PATH).
# Sin ellas Whisper falla con «libcublas.so.12 is not found»; servidor.py entonces pasa a CPU. Añaden ~1,2 GB a la imagen.
RUN pip install --no-cache-dir "nvidia-cublas-cu12" "nvidia-cudnn-cu12==9.*"
WORKDIR /app
COPY servidor.py arranque.sh ./
# Descarga las voces de Piper (https://huggingface.co/rhasspy/piper-voices) en ./voces
VOLUME /voces
EXPOSE 8100
CMD ["sh", "/app/arranque.sh"]
