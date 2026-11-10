# Acceso desde fuera (HTTPS) para una instalación local

Para abrir Jarvis y los enlaces de los correos desde el móvil o desde otra oficina cuando el sistema corre en un PC con Docker Desktop (Windows y WSL). Pensado para `brain.101.cat` (panel) y `auth.101.cat` (inicio de sesión). Para un servidor Linux completo, con Keycloak en producción, ver [DESPLIEGUE.md](DESPLIEGUE.md).

## Antes de empezar (y por qué)

- **Es tu PC en internet.** Solo se publican el panel y el inicio de sesión, por HTTPS; el ERP, Langfuse y la API **no** se publican. Aun así, un PC de trabajo no es un servidor: si puedes, usa Tailscale (sin abrir puertos) o un servidor aparte.
- **Keycloak sigue en modo desarrollo** (su base H2 con volumen propio). Vale para un equipo pequeño; para más usuarios o más tiempo, pasar a `despliegue/docker-compose.produccion.yml` (Keycloak con PostgreSQL).
- **La consola de administración de Keycloak no se abre desde internet** (403): se administra desde este equipo en http://localhost:8080.
- El login ya tiene protección contra fuerza bruta y contraseñas de 12 caracteres o más (`despliegue/configurar_keycloak.py`).

## Requisitos

1. `./scripts/keycloak_conservar.sh` ejecutado (Keycloak con datos permanentes) y la contraseña de administrador rotada (`./scripts/keycloak_clave_admin.sh`).
2. Dos registros **A** en el DNS de `101.cat` (Hostalia): `brain` y `auth`, hacia tu IP pública fija.
3. El **router** reenvía TCP 80 y 443 al PC (con una dirección interna reservada) y tu operador no bloquea el 80 (Let's Encrypt lo necesita para el certificado).
4. Regla de entrada en el **cortafuegos de Windows** para 80 y 443 (PowerShell como administrador):
   `New-NetFirewallRule -DisplayName "Cerebro HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow`

## Si el puerto 80 ya lo usa otro programa

Compruébalo en Windows con `netstat -ano | findstr ":80 :443"` (un `LISTENING` en `0.0.0.0:80` y su número de proceso; `tasklist /fi "PID eq NUMERO"` dice cuál es). Si no puedes cerrar ese programa, activa con `--sin-puerto-80`: el proxy solo publica el 443 hacia fuera (el 80 queda en `127.0.0.1:8088`) y Let's Encrypt valida el certificado por el 443. En el router, reenvía solo el 443. Quien escriba `http://` desde fuera no llegará; `https://` sí.

## Activar

```bash
python3 despliegue/acceso_externo.py activar --panel brain.101.cat --auth auth.101.cat --correo tu@correo --simular   # solo enseña lo que haría
python3 despliegue/acceso_externo.py activar --panel brain.101.cat --auth auth.101.cat --correo tu@correo
```

Fija en `.env` `PANEL_URL`, `KEYCLOAK_URL_PUBLICA`, `DOM_PANEL`, `DOM_AUTH`, `CORREO_ADMIN` y `TLS_MODO`, y añade el proxy (`despliegue/docker-compose.externo.yml`, con `despliegue/Caddyfile.externo`) a `COMPOSE_FILE`; recrea Keycloak, el panel, la API y el proxy y ajusta el cliente de Keycloak. Los valores anteriores quedan en `.acceso-externo.json`. Se detiene antes de tocar nada si Keycloak no conserva sus datos o los nombres aún no resuelven en DNS.

Después de activar, **todos usan `https://brain.101.cat`**, también tú en este PC: el panel vuelve a su dirección pública tras iniciar sesión. Si el router no deja entrar por su propia IP pública, añade en `C:\Windows\System32\drivers\etc\hosts` (como administrador): `127.0.0.1 brain.101.cat auth.101.cat`.

Comprobar: `curl -I https://brain.101.cat` (la primera vez tarda unos segundos en sacar el certificado) y `docker compose logs proxy --tail 30`.

## Volver atrás

```bash
python3 despliegue/acceso_externo.py desactivar
```

Devuelve a `.env` los valores anteriores (sin tocar el resto, como la contraseña de administrador), quita el proxy y vuelve a poner el cliente de Keycloak con `localhost`. Quita también el reenvío del router y la regla del cortafuegos.

## Los enlaces de los correos

Usan `PANEL_URL`, así que con el acceso externo activado salen como `https://brain.101.cat/...` (ver `cerebro/enlaces.py`). Los enlaces a los tratos del CRM usan `CRM_URL_PUBLICA`, que hay que publicar aparte si se quiere abrir el CRM desde fuera (no se publica aquí).
