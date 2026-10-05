# Despliegue en un servidor, con HTTPS

Un solo comando instala el Cerebro completo —Jarvis, Keycloak, Langfuse y ERPNext— detrás de un proxy con HTTPS.

## Qué necesitas

- Un servidor Linux con **Docker y Docker Compose v2**, `python3` con `python3-yaml` y `curl`.
- **Tarjeta NVIDIA** con `nvidia-container-toolkit` (sin ella los modelos van en CPU y cada respuesta tarda minutos).
  Memoria recomendada: 64 GB; disco: 500 GB o más.
- **Cuatro nombres DNS** apuntando al servidor, para un dominio `101.cat`:
  `cerebro.101.cat` (panel), `auth.101.cat` (inicio de sesión), `erp.101.cat` y `trazas.101.cat`.
- Puertos **80 y 443** abiertos hacia internet (con Let's Encrypt) o hacia la red interna (con TLS interno).

## Instalar

```bash
git clone -b claude/new-repository-lqspt7 https://github.com/Ionindustry/cerebro101 && cd cerebro101
./despliegue/desplegar.sh requisitos --dominio 101.cat --tls letsencrypt         # solo comprueba
./despliegue/desplegar.sh instalar --dominio 101.cat --correo it@101.cat \
    --empresa "Razón Social SL" --abreviatura RS \
    --director direccion@101.cat --nombre "Nombre Apellido"
```

`--simular` muestra el plan sin hacer nada. `--tls interno` es para intranet sin DNS público: Caddy firma con su propia
autoridad y el script deja `caddy-raiz.crt`, que hay que instalar como autoridad de confianza en los equipos.
Otras opciones: `--sin-gpu`, `--sin-modelos`, `--sin-erp` (ver `./despliegue/desplegar.sh` sin argumentos).

El script es repetible: no cambia contraseñas ya generadas. Pasos:

1. **`.env`** con contraseñas aleatorias, las direcciones del dominio y `CEREBRO_MODO=produccion` (permisos 600).
2. **Base y modelos de IA** (Postgres, Redis, Ollama; descarga de los modelos del perfil).
3. **Servicios**: API, worker, panel, Langfuse v3, Keycloak en modo producción con su propia base de datos, y las
   migraciones (que crean el rol de mínimo privilegio de la base de datos).
4. **ERPNext**: instalación, asistente inicial, usuarios técnicos de Dirección y Finanzas y blindaje contra validar o borrar.
5. **Keycloak**: direcciones del panel, protección contra fuerza bruta, contraseñas de 12+ caracteres y el primer usuario
   de dirección con una **contraseña temporal que se muestra una sola vez**.
6. **Proxy Caddy** con HTTPS automático.
7. **Verificación**: responden el panel, Keycloak (con el emisor https correcto), ERPNext y Langfuse; la API y los permisos de la base de datos.

## Seguridad del despliegue

- **Solo Caddy escucha hacia fuera** (80 y 443). Todo lo demás escucha en `127.0.0.1` o en la red interna de Docker; una
  prueba automática lo vigila. Docker ignora el cortafuegos para los puertos publicados, por eso importa.
- **La consola de administración de Keycloak** (`/admin`, `/realms/master`) solo se abre desde `IPS_ADMIN` (por defecto,
  redes privadas). El inicio de sesión de los usuarios sigue abierto. Para restringirlo a una IP: `IPS_ADMIN=203.0.113.7` en `.env`.
- **El registro de usuarios** está desactivado en Keycloak y en Langfuse. Los usuarios los crea un administrador.
- Cabeceras de seguridad (HSTS, `nosniff`, política de referencias) y sin cabecera `Server`.
- La API no se publica: el panel habla con ella por la red interna.
- Cortafuegos del servidor: `ufw allow OpenSSH && ufw allow 80,443/tcp && ufw allow 443/udp && ufw enable`.

## Mantenimiento

```bash
./despliegue/desplegar.sh estado        # contenedores y comprobaciones
./despliegue/desplegar.sh actualizar    # git pull, reconstruye y reinicia (las migraciones se aplican solas)
./despliegue/desplegar.sh copia         # copia de seguridad (ver scripts/copia_seguridad.sh)
```

Copia nocturna recomendada (y llevad `copias/` fuera del servidor): `0 3 * * *  cd /ruta/cerebro101 && ./scripts/copia_seguridad.sh --parar`.
**Guardad una copia del `.env` en un gestor de contraseñas**: no está en git y sin él no se pueden usar las copias.
Los certificados viven en el volumen `caddy-datos`: conservadlo para no volver a pedirlos en cada arranque.

## Problemas frecuentes

| Síntoma | Causa probable |
| --- | --- |
| El navegador avisa de certificado no válido | Con `--tls interno`, falta instalar `caddy-raiz.crt`. Con Let's Encrypt: el DNS no apunta al servidor o el puerto 80 está cerrado (`docker compose logs proxy`) |
| Let's Encrypt rechaza por límite de peticiones | Demasiados intentos fallidos: esperad una hora o probad antes con `--tls interno` |
| «503» al abrir `auth.…` justo tras instalar | Keycloak aún arranca (1-2 minutos); `docker compose logs keycloak` |
| El panel vuelve al inicio de sesión una y otra vez | `PANEL_URL` no coincide con la dirección que se usa, o no se ejecutó `configurar_keycloak.py` |
| Jarvis tarda minutos en responder | No hay GPU o Ollama no la ve (`nvidia-smi` dentro del contenedor) |

## Qué se ha probado y qué no

Probado en un entorno de pruebas (sin GPU) con el dominio ficticio `prueba.test` y TLS interno:
- Generación del `.env` (17 pruebas automáticas) y validación del compose y del Caddyfile.
- Keycloak 26 en modo producción con su base de datos y detrás de Caddy: emisor `https://auth…`, importación del realm,
  configuración del cliente, restricción de la consola de administración (403 desde una IP no permitida, 200 desde una permitida).
- **Inicio de sesión real en un navegador** por HTTPS: panel → Keycloak → contraseña temporal y cambio obligatorio → panel con
  la sesión → la API acepta el token → cierre de sesión.
- Rutas a ERPNext y Langfuse, redirección de http a https, certificado de la CA interna y cabeceras de seguridad.

**No probado** (requiere un servidor real): la ejecución completa de `desplegar.sh instalar` de principio a fin, la emisión
de certificados con Let's Encrypt, la comprobación de la GPU y de `nvidia-container-toolkit`, `actualizar` y `estado`. Hacedlo
primero con `--simular` y, si es posible, en un servidor de pruebas con `--tls interno`.
