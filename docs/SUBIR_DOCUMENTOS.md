# Subir documentos al chat de Jarvis

En el chat de Jarvis, el botón 📎 sube un documento (PDF, Word, Excel `.xlsx`, OpenDocument, CSV o texto, hasta 25 MB) y se adjunta al mensaje que escribas a continuación. Jarvis **lee su texto** con la herramienta
`documentos_subidos`; no recibe el fichero.

## Qué pasa con el documento
1. **Se comprueba qué es por su contenido**, no por el nombre. Se rechazan ZIP, Excel/Word antiguos (`.xls`, `.doc`), HTML, ejecutables y cualquier otra cosa.
2. **Cuarentena y antivirus (ClamAV)**, como los pliegos de las licitaciones. Si el antivirus no está disponible, tiene las firmas viejas o marca el documento, **no se ofrece a nadie**.
3. **El texto se extrae en un proceso aparte**, sin secretos y con límites de tiempo y memoria (con OCR si es un escaneo). Un CSV se lee como texto, en bloques de filas que repiten la cabecera.
4. **Solo quien lo subió puede adjuntarlo a un mensaje.** El sistema (no el usuario ni el modelo) añade a la petición el id y el nombre; el contenido es dato, nunca instrucciones.
5. **Se borra a los 30 días** (el fichero y su texto): `subidas.retencion_dias` en `config/integraciones.yaml`. Límite de 40 subidas por persona y día.

## Quién puede leerlos
Los agentes **Catálogo de Proveedores** y **Compras** (departamento Operaciones). Para dárselo a otro agente, añade `documentos_subidos` a sus herramientas en `scripts/generar_fichas.py` y ejecuta el script.

## Para quien administra
- Carpeta: `SUBIDAS_DIR` (por defecto `/datos/subidas`, volumen `datos`).
- Tablas: `documentos_subidos` y `documentos_subidos_paginas` (se crean solas al arrancar).
- La ruta `/cerebro/documentos/subir` queda fuera del middleware del panel (Next recorta a 10 MB lo que lo atraviesa); la pasarela exige la sesión igualmente.
