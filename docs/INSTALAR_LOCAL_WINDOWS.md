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
  Para traer los datos de otra máquina: `./scripts/migracion.sh importar paquete.tar.gz --confirmar` (con el `.env` del origen copiado antes; ver [SERVIDOR_A2000.md](SERVIDOR_A2000.md)).
- **Los secretos**: `.env` está fuera de Git a propósito. Nunca lo subas ni lo pegues en un chat.
- **Los ficheros de entornos restringidos** (`docker-compose.override.yml`, `Dockerfile.local`, `ca.crt`): solo hacían falta en el entorno
  de desarrollo en la nube. En tu PC no.

## Arranque automático y recuperación si Docker se cae
Dos piezas, ya incluidas en el proyecto:
- `scripts/arrancar.sh` (dentro de WSL): levanta el Cerebro y el ERP ya instalados, sin reconstruir nada, y espera a que respondan. Se puede lanzar a mano
  (`./scripts/arrancar.sh`) o solo para comprobar (`./scripts/arrancar.sh estado`). Si Docker se ha caído y has vuelto a abrirlo, es lo único que necesitas.
- `scripts/windows/autoarranque.ps1` (en Windows): registra dos tareas programadas. **Arranque**: al iniciar sesión abre Docker Desktop y lanza `arrancar.sh`.
  **Vigilante**: cada 5 minutos comprueba Docker y la API; si Docker no responde dos veces seguidas (10 minutos) lo cierra, reinicia WSL y lo vuelve a abrir
  (máximo 3 veces por hora, para no entrar en bucle); si Docker responde pero la API no, vuelve a levantar los servicios.

Instalarlo (una vez). Desde Ubuntu, copia el script a Windows:
```
cp ~/cerebro101/scripts/windows/autoarranque.ps1 /mnt/c/Users/$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')/
```
y en **PowerShell como administrador** (cambia la ruta si tu usuario no es `PC`):
```
powershell -ExecutionPolicy Bypass -File C:\Users\PC\autoarranque.ps1 -Instalar
powershell -ExecutionPolicy Bypass -File C:\Users\PC\autoarranque.ps1 -Estado
```
`-Estado` muestra si las dos tareas existen, si Docker y la API responden y las últimas líneas del registro (`%USERPROFILE%\cerebro-autoarranque\autoarranque.log`).
Para quitarlo: `-Quitar`. Para probarlo sin reiniciar: `Start-ScheduledTask -TaskName "Cerebro - arranque"`.

Límites que conviene conocer: Docker Desktop necesita una sesión de usuario abierta (tras reiniciar el PC hay que iniciar sesión, o activar el inicio de
sesión automático); si el PC se suspende, todo se para (`powercfg /change standby-timeout-ac 0`); y el script de Windows **no se ha podido probar en un
Windows real desde el entorno donde se escribió**: la parte de WSL (`arrancar.sh`) sí está probada.

## Copias de seguridad

Haz una copia **antes de cada actualización** y, mientras el PC se cuelgue de vez en cuando, una vez por semana. Desde la raíz del repositorio, en Ubuntu:

```
COPIA_SIN_TRAZAS=1 ./scripts/copia_seguridad.sh
```

Guarda en `copias/<fecha>/` las bases de datos del Cerebro y de Langfuse, la del motor de licitaciones si está en marcha y las sumas de control (`SHA256SUMS`). `COPIA_SIN_TRAZAS=1` se salta las trazas de Langfuse, que son lo que más pesa. Copia esa carpeta de vez en cuando a otro disco o a la nube: una copia que está en el mismo PC no protege de un fallo del PC. Guarda también tu `.env` en un gestor de contraseñas. Para recuperar una base: `gunzip -c copias/<fecha>/cerebro.sql.gz | docker compose exec -T postgres psql -U cerebro cerebro` (en una base vacía).

## Actualizar sin construir en tu PC

Construir las imágenes en tu PC es lo que más lo castiga (procesador y disco al máximo durante minutos). GitHub puede construirlas por ti: cada vez que se fusiona un cambio en `main`, la pestaña **Actions** del repositorio (flujo «Imágenes») las construye y las publica en `ghcr.io`; tu PC solo las descarga.

**Una vez:**

1. En GitHub → tu foto → *Settings* → *Developer settings* → *Personal access tokens* → *Tokens (classic)* → *Generate new token (classic)*. Dale solo el permiso **`read:packages`**. Cópialo (no lo pegues en ningún chat ni lo guardes en el repositorio).
2. En Ubuntu: `docker login ghcr.io -u TU_USUARIO_DE_GITHUB`. Cuando pida la contraseña, pega el token (no se ve al pegarlo). Debe decir «Login Succeeded».
3. En el `.env`, añade (están comentadas en `.env.example`; cambia `ionindustry` si tu propietario en GitHub es otro):
   ```
   CEREBRO_IMAGEN_API=ghcr.io/ionindustry/cerebro101-api:main
   CEREBRO_IMAGEN_PANEL=ghcr.io/ionindustry/cerebro101-panel:main
   LIC_IMAGEN=ghcr.io/ionindustry/cerebro101-licitaciones:main
   ```

**Cada actualización:** espera a que el flujo «Imágenes» del último cambio termine en verde (unos minutos; pestaña Actions) y ejecuta

```
./scripts/actualizar.sh
```

Trae el código, descarga las imágenes (si falla, reintenta; lo ya descargado no se vuelve a bajar), reinicia el motor y el Cerebro y enseña el estado. Sin las tres líneas del `.env`, el mismo script construye en tu PC como siempre. Si una imagen no se descarga: ¿hiciste el `docker login`?, ¿terminó de construirse en GitHub?

Si GitHub dice que no tiene permiso para el paquete (la primera vez), en *Packages* del repositorio abre cada paquete → *Package settings* → «Manage Actions access» y añade este repositorio con permiso de escritura.

## Problemas típicos

| Síntoma | Causa y solución |
| --- | --- |
| `could not select device driver "nvidia"` | No hay GPU para Docker: usa `docker-compose.sin-gpu.yml` (paso 3) |
| `bad interpreter: /bin/bash^M` o `\r: command not found` | Clonaste en Windows y los `.sh` tienen saltos de línea CRLF. Vuelve a clonar dentro de WSL |
| Jarvis responde «el modelo de IA no está disponible» o tarda minutos | Ollama sin memoria o sin modelos: `docker compose logs ollama` y `curl localhost:8000/salud/modelos`. Cierra ERPNext si no lo usas |
| Docker Desktop se queda sin memoria | Sube el límite en `%UserProfile%\.wslconfig` (`[wsl2]` → `memory=12GB`) y ejecuta `wsl --shutdown` |
| Error 429 al descargar imágenes | Límite de Docker Hub: espera unos minutos o inicia sesión con `docker login` |
