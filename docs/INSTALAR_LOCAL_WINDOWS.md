# Instalar el Cerebro en un PC con Windows (pruebas y desarrollo)

Para probar y trabajar en local. Un servidor real, con HTTPS y todo lo demás, se monta con [DESPLIEGUE.md](DESPLIEGUE.md).

## Qué necesitas

| Cosa | Para qué |
| --- | --- |
| Windows 10/11 con **WSL2** (`wsl --install`) | Los scripts del proyecto son de bash |
| **Docker Desktop** con «Use WSL 2 based engine» | Todos los servicios van en contenedores |
| Git | Clonar el repositorio |
| 16 GB de RAM como mínimo y unos 40 GB de disco | Ollama, Langfuse, ERPNext y la base de datos conviven |
| Tarjeta NVIDIA (opcional) | Sin ella funciona, pero cada respuesta tarda decenas de segundos o minutos |

Trabaja **dentro de WSL** (terminal «Ubuntu»), no en PowerShell: `git clone` en `~/cerebro101`, no en `C:\Users\…`. Los ficheros de
`C:` desde Docker son mucho más lentos y los scripts `.sh` pueden romperse por los saltos de línea de Windows.

## 1. Clonar

```bash
git clone -b claude/new-repository-lqspt7 https://github.com/ionindustry/cerebro101.git ~/cerebro101
cd ~/cerebro101
```

Si el repositorio es privado, Git pedirá el usuario de GitHub y un token personal.

## 2. Crear el `.env`

```bash
python3 despliegue/preparar_env.py
```

Genera todas las contraseñas y claves y deja el fichero con permisos 600. **No pisa lo que ya hayas rellenado**, así que se puede repetir.
Después, a mano en `.env`:

- `JEV_API_KEY`, `XAI_API_KEY`, `CORREO_*` y `CALENDARIO_*` si vas a usarlos (no se generan).
- `PERFIL_HARDWARE=pequena` (12–16 GB de memoria de vídeo o sin GPU) o `grande` (24 GB o más).
- Para probar sin crear usuarios en Keycloak: `CEREBRO_MODO=desarrollo` y `PANEL_USUARIO_DESARROLLO=tu-nombre`.
  **Solo en tu PC**: en ese modo cualquiera que llegue a la API se identifica con una cabecera.

## 3. Arrancar

Con tarjeta NVIDIA (y su soporte en WSL2/Docker Desktop):

```bash
./scripts/iniciar.sh
```

Sin tarjeta, usa el fichero que quita la reserva de GPU:

```bash
echo "COMPOSE_FILE=docker-compose.yml:docker-compose.sin-gpu.yml" >> .env
./scripts/iniciar.sh
```

La primera vez descarga imágenes y los modelos de Ollama (varios GB): tarda. Después:

| Servicio | Dirección |
| --- | --- |
| Panel de Jarvis | http://localhost:3000 |
| API (documentación) | http://localhost:8000/docs |
| Keycloak | http://localhost:8080 |
| Langfuse (registro) | http://localhost:3001 |

Comprueba que todo responde: `curl localhost:8000/salud` y `curl localhost:8000/salud/modelos` (dice qué modelos faltan).

## 4. ERPNext

El ERP va en su propio stack (`erpnext/docker-compose.yml`) en la misma red `cerebro`. Los pasos (asistente inicial, usuarios técnicos,
blindaje) están en [INSTALACION.md](INSTALACION.md), punto 6. Con 16 GB de RAM, **arráncalo solo cuando lo necesites**: junto con
Ollama y Langfuse deja la máquina sin memoria y los modelos empiezan a dar timeouts.

## Lo que NO viene en el repositorio

- **Los datos**: bases de datos, trazas, sesiones y modelos descargados viven en volúmenes de Docker de cada máquina. Un clon empieza vacío:
  el servicio `migraciones` crea las tablas y hay que repetir el asistente de ERPNext y cargar los documentos de conocimiento.
- **Los secretos**: `.env` está fuera de Git a propósito. Nunca lo subas ni lo pegues en un chat.
- **Los ficheros de entornos restringidos** (`docker-compose.override.yml`, `Dockerfile.local`, `ca.crt`): solo hacían falta en el entorno
  de desarrollo en la nube. En tu PC no.

## Problemas típicos

| Síntoma | Causa y solución |
| --- | --- |
| `could not select device driver "nvidia"` | No hay GPU para Docker: usa `docker-compose.sin-gpu.yml` (paso 3) |
| `bad interpreter: /bin/bash^M` o `\r: command not found` | Clonaste en Windows y los `.sh` tienen saltos de línea CRLF. Vuelve a clonar dentro de WSL |
| Jarvis responde «el modelo de IA no está disponible» o tarda minutos | Ollama sin memoria o sin modelos: `docker compose logs ollama` y `curl localhost:8000/salud/modelos`. Cierra ERPNext si no lo usas |
| Docker Desktop se queda sin memoria | Sube el límite en `%UserProfile%\.wslconfig` (`[wsl2]` → `memory=12GB`) y ejecuta `wsl --shutdown` |
| Error 429 al descargar imágenes | Límite de Docker Hub: espera unos minutos o inicia sesión con `docker login` |
