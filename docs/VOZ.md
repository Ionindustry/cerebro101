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

## Si algo falla

| Síntoma | Mira |
|---|---|
| «Falta la voz …» | Descarga las voces (arriba) |
| «El servicio de voz no responde» | `docker compose ps voz` y `docker compose logs --tail 30 voz` |
| «El navegador ha bloqueado el audio» | Pulsa en la página y vuelve a probar |
| No te transcribe | Mira que la barra de nivel se mueva al hablar (micrófono) y `docker compose logs voz` |
| Estado del servicio | `docker compose exec voz python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8100/salud').read())"` (dispositivo de Whisper y voces presentes) |
