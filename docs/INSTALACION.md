# Instalación

## Requisitos

- Servidor Linux con Docker y Docker Compose
- Tarjeta NVIDIA con controladores y NVIDIA Container Toolkit (`nvidia-smi` debe funcionar dentro de Docker)
- 64 GB de RAM y 2 TB de SSD recomendados

## Pasos

1. `cp .env.example .env` y rellenar contraseñas. Elegir `PERFIL_HARDWARE` según la memoria de la tarjeta.
2. Descargar las voces de Piper en catalán y castellano en `servicios/voz/voces/`
   (https://huggingface.co/rhasspy/piper-voices).
3. `./scripts/iniciar.sh`
4. Entrar en Keycloak (http://localhost:8080, usuario `admin` y `KEYCLOAK_ADMIN_PASSWORD`), realm `cerebro`: crear los
   usuarios, asignar roles (`direccion`, `responsable`, `usuario`) y grupos de departamento. El panel pide ese
   inicio de sesión al entrar (http://localhost:3000). Fuera de localhost, poner en `.env` `PANEL_URL` y
   `KEYCLOAK_URL_PUBLICA` con sus direcciones https y añadir `PANEL_URL/*` en las URI del cliente `cerebro-panel`.
5. Cargar documentos: `docker compose exec api python /app/scripts/cargar_conocimiento.py /datos/conocimiento`.
6. ERPNext: instalar con [frappe_docker](https://github.com/frappe/frappe_docker) en la red `cerebro`, crear un
   usuario técnico por departamento con sus roles y poner sus tokens en `.env`.
7. Integraciones: en `config/integraciones.yaml`, poner el servidor IMAP/SMTP y la URL CalDAV del servidor de
   correo propio, y las URL de sindicación (ATOM) de las plataformas de contratación. Las cuentas van en `.env`
   (`CORREO_*`, `CALENDARIO_*`). Se recomienda una cuenta técnica por departamento, con acceso solo a su buzón.

## Comprobación

```bash
curl http://localhost:8000/salud
# {"estado":"ok","agentes":114,"departamentos":13,...}
```
