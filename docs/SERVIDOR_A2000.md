# Pasar el proyecto a un servidor con una NVIDIA RTX A2000

La A2000 existe en **dos versiones, de 6 GB y de 12 GB**, y con eso decide qué modelos caben. Compruébalo en el servidor:

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
```

| Tarjeta | Perfil | Modelos | Qué esperar (estimación, sin medir en esta tarjeta) |
| --- | --- | --- | --- |
| A2000 6 GB | `minima` | `qwen3.5:4b` para todo (3,3 GB) + `bge-m3` (1,2 GB) | Respuestas en pocos segundos; el modelo de 4B se equivoca más que el de 9B en herramientas y razonamiento |
| A2000 12 GB | `mediana` | `qwen3.5:9b` para todo (6,6 GB) + `bge-m3` | Unos 20–30 tokens por segundo (ancho de banda de 288 GB/s); una respuesta de agente, 10–40 s |

`despliegue/desplegar.sh` elige el perfil solo a partir de `nvidia-smi`, y ajusta Ollama (peticiones simultáneas, modelos cargados) y la voz
(Whisper `small` en vez de `large-v3-turbo`, que no cabe junto al modelo). Se puede forzar con `--perfil minima|mediana|pequena|grande`.
Los perfiles `pequena` y `grande` (16 y 24 GB) **no** caben en una A2000.

## 1. Preparar el servidor (una vez)

Pensado para Ubuntu 22.04/24.04. **Estos comandos son los de la documentación oficial de Docker y NVIDIA; no los he podido ejecutar en una
tarjeta real desde mi entorno**, así que revisa su salida.

```bash
# Controladores NVIDIA (si nvidia-smi ya funciona, salta este paso)
sudo ubuntu-drivers install && sudo reboot

# Docker y Compose v2
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker "$USER"      # cierra sesión y vuelve a entrar

# NVIDIA Container Toolkit: la tarjeta visible desde los contenedores
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit python3-yaml curl git
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker

# Prueba: debe mostrar la A2000 desde dentro de un contenedor
docker run --rm --gpus all ubuntu nvidia-smi
```

Si ese último comando falla, nada de lo demás funcionará con GPU: arréglalo antes de seguir.

## 2. Llevar el proyecto al servidor

El código, la configuración, los 114 agentes, las pruebas y la documentación están en GitHub, rama `claude/new-repository-lqspt7`. Es la vía normal:

```bash
git clone -b claude/new-repository-lqspt7 https://github.com/ionindustry/cerebro101.git
cd cerebro101
```

Si el repositorio es privado, Git pide el usuario y un token personal de GitHub. Si el servidor no tiene acceso a GitHub, genera un paquete en
cualquier equipo que sí lo tenga y cópialo:

```bash
git clone -b claude/new-repository-lqspt7 https://github.com/ionindustry/cerebro101.git && cd cerebro101
git bundle create ../cerebro101.bundle --all                       # en el equipo con acceso
scp ../cerebro101.bundle usuario@servidor:~                        # y en el servidor:
git clone -b claude/new-repository-lqspt7 ~/cerebro101.bundle cerebro101
```

### Qué NO se transfiere (y por qué)

| Cosa | Qué hacer |
| --- | --- |
| `.env` (contraseñas y claves) | No está en Git. `desplegar.sh instalar` lo crea con claves aleatorias nuevas. La clave de Jev y las de correo/Grok se ponen a mano |
| Datos de este entorno de desarrollo (bases, trazas, ERPNext de pruebas) | No merece la pena: son datos de prueba. El servidor empieza limpio; las migraciones crean las tablas |
| Modelos de Ollama | Se descargan en el servidor (`qwen3.5:4b` ≈ 3,3 GB o `qwen3.5:9b` ≈ 6,6 GB, más `bge-m3`) |
| Documentos de conocimiento | Se cargan con `scripts/cargar_conocimiento.py` (ver `docs/INSTALACION.md`, paso 5) |

Para mover **datos reales** de un servidor a otro más adelante existe `scripts/copia_seguridad.sh` (volcados de PostgreSQL, Langfuse, ERPNext y
trazas). La restauración **todavía no está automatizada**: hoy se hace a mano con `psql`/`tar`. Dime si quieres que la escriba.

## 3. Instalar

```bash
./despliegue/desplegar.sh requisitos --dominio 101.cat            # comprueba GPU, Docker, DNS… e indica el perfil elegido
./despliegue/desplegar.sh instalar --dominio 101.cat --correo it@101.cat \
    --empresa "Razón Social SL" --abreviatura RS --director direccion@101.cat --nombre "Nombre Apellido"
```

Los cuatro nombres DNS (`cerebro.`, `auth.`, `erp.`, `trazas.` + dominio) y los puertos 80/443 se explican en [DESPLIEGUE.md](DESPLIEGUE.md).
Sin dominio (solo pruebas en la red local): `--tls interno` o, para ni siquiera HTTPS, [INSTALACION.md](INSTALACION.md).

## 4. Comprobar que la tarjeta se usa de verdad

```bash
docker compose exec ollama ollama ps          # la columna PROCESSOR debe decir «100% GPU»
nvidia-smi                                    # memoria usada: no debe llegar al máximo
curl -s localhost:8000/salud/modelos          # modelos del perfil descargados
```

| Si ves… | Haz… |
| --- | --- |
| `PROCESSOR` con `% CPU` | El modelo no cabe entero: baja `OLLAMA_NUM_CTX` a 4096 en `.env`, o usa el perfil `minima` |
| Memoria de la tarjeta al máximo y errores «model runner has unexpectedly stopped» | Lo mismo, y `OLLAMA_NUM_PARALLEL=1` |
| La voz falla al arrancar por memoria | `WHISPER_DISPOSITIVO=cpu` en `.env` (más lenta, no usa la tarjeta) |

Tras cambiar el `.env`: `docker compose up -d ollama voz api worker`.

## 5. Medir con los modelos reales

Todas las mediciones del repositorio (enrutado 64 %, herramientas 13/16, calidad) se hicieron con un modelo de 3B **en CPU**. Con la tarjeta real
hay que repetirlas, que es lo que dirá si el perfil elegido basta:

```bash
docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/evaluar_enrutado.py
docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/evaluar_herramientas.py --modos nuevo
docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/evaluar_calidad.py
docker compose exec -e PYTHONPATH=/app/api api python /app/scripts/probar_aprobacion_doble.py
```

Los resultados se comparan con las tablas de `evaluacion/README.md`. Si el enrutado o la calidad se quedan cortos con `minima`, el siguiente paso
es una tarjeta de más memoria, no más prompts.
