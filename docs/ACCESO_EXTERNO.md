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

## Docker Desktop en Windows: el reenviador y la redirección del 443

En Docker Desktop (Windows con WSL), el puerto 443 **publicado por el propio proxy se cortaba justo después del saludo HTTPS**, tanto desde el navegador como desde fuera, mientras que el mismo reenvío hecho por **otro contenedor desde la red interna** funcionaba. Por eso el proxy no publica el 443: lo hace un pequeño reenviador (`reenvio`, `socat` fijado por su huella SHA-256, TCP puro: el contenido sigue cifrado hasta Caddy). Se activa con `--puerto-https 18443` y Windows redirige su 443 a ese puerto:

```powershell
# PowerShell COMO ADMINISTRADOR (sustituye 192.168.1.102 por la dirección interna fija de este PC)
New-NetFirewallRule -DisplayName "Cerebro HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
netsh interface portproxy add v4tov4 listenaddress=192.168.1.102 listenport=443 connectaddress=127.0.0.1 connectport=18443
netsh interface portproxy show all
```

- El **router** sigue reenviando el 443 externo al 443 de ese PC; el resto va por dentro.
- En el `hosts` de este PC usa **la dirección del PC** (`192.168.1.102 brain.101.cat auth.101.cat`) y no `127.0.0.1`: en `127.0.0.1:443` puede escuchar otro programa de Windows (un reenviador de WSL) que no habla con el proxy. Edítalo con PowerShell como administrador (no reescribas el fichero con un `-replace`; añade o reconstruye la línea).
- El puerto 80 puede estar ocupado por una regla vieja de `netsh interface portproxy` (míralo con `netsh interface portproxy show all`): con `--sin-puerto-80` no hace falta.
- La regla de `netsh` y la dirección fija del PC son lo que sostiene el acceso: reserva la dirección en el router.

### Que no se rompa tras reiniciar el PC

La cadena completa tiene varios eslabones, y cada uno se arregla solo o lo vigila algo:

| Eslabón | Si falla | Quién lo arregla |
|---|---|---|
| Docker Desktop | el motor no arranca | la tarea «Cerebro - arranque» y el vigilante de `scripts/windows/autoarranque.ps1` |
| Servicios del Cerebro (panel, API, Keycloak…) | están parados | `scripts/arrancar.sh` (lo lanzan las tareas anteriores) |
| Reenviador y proxy (contenedores `reenvio` y `proxy`) | se paran | `restart: unless-stopped` |
| **Regla de Windows (`netsh portproxy`) sin escuchar tras arrancar** | desde fuera no se llega (el servicio «Ayudante de IP» arranca antes que la red) | **`scripts/windows/reenvio_https.ps1 -Instalar -Dominios …`**: tarea como SYSTEM que al arrancar y cada 5 minutos comprueba que Windows escucha en el 443 y, si no, reinicia `iphlpsvc`; además pide la página de verdad y, si no responde, la repara por escalones (ver abajo) |
| Dirección interna del PC | la regla apunta a otra | reserva de la dirección en el router; el vigilante lo anota en su registro |
| Suspensión del PC | todo se para | «Suspensión: Nunca» |

Instalar el vigilante del reenvío (PowerShell COMO ADMINISTRADOR):

```powershell
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\pc\cerebro101\scripts\windows\reenvio_https.ps1 -Instalar -Dominios "brain.101.cat,auth.101.cat"
powershell -ExecutionPolicy Bypass -File C:\ProgramData\Cerebro\reenvio_https.ps1 -Estado
```

Copia el script a `C:\ProgramData\Cerebro` (la tarea no depende de WSL para arrancar) y deja su registro en `C:\ProgramData\Cerebro\reenvio-https.log`. Solo actúa si existe una regla del 443; `-Quitar` borra la tarea. `-Estado` hace además una prueba en vivo de la página.

**Qué repara solo, de menos a más** (cada 5 minutos; con `-Dominios`):

1. Windows no escucha en el 443 → reinicia `iphlpsvc`.
2. Faltan los dominios en el archivo `hosts` → los añade con la IP del PC.
3. Pide `https://brain.101.cat` de verdad. Si responde (200, 302, 502…), no hace nada más.
4. Si Docker responde en el 18443 pero Windows no → recrea la regla `netsh` y reinicia `iphlpsvc`.
5. Si Docker tampoco responde → reinicia los contenedores `reenvio` y `proxy` (como mucho uno cada 10 minutos y 6 al día, para no reiniciar en bucle).
6. Si aun así no responde, lo anota como `REQUIERE ATENCION` en el registro (lo normal: Docker Desktop cerrado; ábrelo y espera a «Engine running»).

Lo que **no** hace: reiniciar Docker Desktop ni WSL, porque cortaría trabajos largos en curso (como «Preparar la oferta»). Para que Docker Desktop arranque solo, activa en su configuración «Start Docker Desktop when you sign in».

### Si ya tienes el acceso activado con una «sonda» manual (`sonda-443`)

```bash
git checkout despliegue/docker-compose.externo.yml     # por si lo editaste a mano
git pull --ff-only
docker rm -f sonda-443                                  # libera el puerto 18443
python3 despliegue/acceso_externo.py puerto 18443       # el reenviador oficial lo sustituye
```

## Activar

```bash
python3 despliegue/acceso_externo.py activar --panel brain.101.cat --auth auth.101.cat --correo TU_CORREO_REAL --puerto-https 18443 --sin-puerto-80 --simular   # solo enseña lo que haría
python3 despliegue/acceso_externo.py activar --panel brain.101.cat --auth auth.101.cat --correo TU_CORREO_REAL --puerto-https 18443 --sin-puerto-80
```

Fija en `.env` `PANEL_URL`, `KEYCLOAK_URL_PUBLICA`, `DOM_PANEL`, `DOM_AUTH`, `CORREO_ADMIN` y `TLS_MODO`, y añade el proxy (`despliegue/docker-compose.externo.yml`, con `despliegue/Caddyfile.externo`) a `COMPOSE_FILE`; recrea Keycloak, el panel, la API y el proxy y ajusta el cliente de Keycloak. Los valores anteriores quedan en `.acceso-externo.json`. Se detiene antes de tocar nada si Keycloak no conserva sus datos, los nombres aún no resuelven en DNS o el correo es de ejemplo (usa el tuyo: Let's Encrypt lo usa para avisarte).

Después de activar, **todos usan `https://brain.101.cat`**, también tú en este PC: el panel vuelve a su dirección pública tras iniciar sesión. Si el router no deja entrar por su propia IP pública, añade en `C:\Windows\System32\drivers\etc\hosts` (como administrador): `127.0.0.1 brain.101.cat auth.101.cat`.

Comprobar: `curl -I https://brain.101.cat` (la primera vez tarda unos segundos en sacar el certificado) y `docker compose logs proxy --tail 30`.

## Volver atrás

```bash
python3 despliegue/acceso_externo.py desactivar
```

Devuelve a `.env` los valores anteriores (sin tocar el resto, como la contraseña de administrador), quita el proxy y vuelve a poner el cliente de Keycloak con `localhost`. Quita también el reenvío del router y la regla del cortafuegos.

## Los enlaces de los correos

Usan `PANEL_URL`, así que con el acceso externo activado salen como `https://brain.101.cat/...` (ver `cerebro/enlaces.py`). Los enlaces a los tratos del CRM usan `CRM_URL_PUBLICA`, que hay que publicar aparte si se quiere abrir el CRM desde fuera (no se publica aquí).
