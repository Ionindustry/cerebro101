Aquí vive `buzones.env`, con las contraseñas de los buzones de correo de la empresa (una línea `CORREO_<BUZON>_CLAVE=...` por buzón).
No se sube a git (ver `.gitignore` de esta carpeta). Se crea y se mantiene con `python3 scripts/buzon_alta.py`; guía completa en `docs/CORREO.md`.

También puede haber `tarifas.env` (claves de servicios web de proveedores) y `eet.env` (acceso a EET Europarts: `EET_CLIENTE=<tu número de cliente>` y `EET_CLAVE=<tu AuthCode>`; ver `docs/EET.md`). Se crean a mano en tu servidor; nunca en git ni en el chat.
