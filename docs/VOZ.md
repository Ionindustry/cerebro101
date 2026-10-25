# Voz de Jarvis

Jarvis te escucha (voz a texto con Whisper) y te contesta en voz alta (texto a voz con Piper). Todo corre en tu servidor, sin enviar audio fuera.

## Hablarle

- Elige el micrófono (por ejemplo, el de la webcam) en la lista **Micrófono** de Jarvis y pulsa el botón del micrófono; vuelve a pulsarlo para terminar.
- Whisper usa la tarjeta gráfica si tiene las librerías de NVIDIA (están en la imagen); si no puede, pasa solo a la CPU con el modelo `small` y lo cuenta en el log (`docker compose logs voz`).

## Que te conteste por voz

- El interruptor **Respuesta por voz** (junto al micrófono) está activo por defecto: Jarvis lee en alto cada respuesta, también las de preguntas escritas. Se recuerda en el navegador. **Callar** corta lo que esté diciendo; si le hablas, se calla solo.
- Se lee el texto limpio (sin marcas de formato, enlaces ni código) y como máximo unas frases: las respuestas larguísimas se cortan al final de una frase. La voz es catalana si el texto lo parece y castellana en otro caso.
- **Las voces hay que descargarlas una vez**, en el servidor (no vienen en el repositorio, pesan unos 60 MB cada una):

  ```bash
  python3 scripts/voces_descargar.py
  docker compose restart voz
  ```

  Si falta la voz, Jarvis lo dice en pantalla en vez de quedarse mudo.

## Cambiar la voz (por ejemplo, una voz femenina en castellano)

La voz de salida en catalán (`upc_ona`) es femenina. La de castellano que se instala por defecto (`davefx`) es masculina. Hay una alternativa con locutora, `es_ES-sharvard-medium`, que trae dos locutores (M y F):

```bash
python3 scripts/voces_descargar.py --solo es-sharvard
```

Después, en el `.env`:

```
PIPER_VOZ_ES=/voces/es_ES-sharvard-medium.onnx
PIPER_LOCUTOR_ES=F
```

y `docker compose up -d --force-recreate voz`. Si la voz no suena como esperas, prueba `PIPER_LOCUTOR_ES=M`, o los números `0` y `1`. Si el nombre del locutor no existe, Jarvis dice en pantalla cuáles hay. Para volver a la de siempre, borra esas dos líneas y recrea la voz. Otras voces: https://huggingface.co/rhasspy/piper-voices (cada una son dos ficheros, `.onnx` y `.onnx.json`, que van a `servicios/voz/voces/`).

*Sin verificar:* la voz `sharvard` y sus locutores no se han podido oír desde el entorno de desarrollo; si ninguno te convence, dímelo y se prueba otra.

## Si algo falla

| Síntoma | Mira |
|---|---|
| «Falta la voz …» | Descarga las voces (arriba) |
| «El servicio de voz no responde» | `docker compose ps voz` y `docker compose logs --tail 30 voz` |
| «El navegador ha bloqueado el audio» | Pulsa en la página y vuelve a probar |
| No te transcribe | Mira que la barra de nivel se mueva al hablar (micrófono) y `docker compose logs voz` |
| Estado del servicio | `docker compose exec voz python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8100/salud').read())"` (dispositivo de Whisper y voces presentes) |
