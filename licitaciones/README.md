# Motor de licitaciones

Código del motor de búsqueda de licitaciones (Go). El proyecto, las decisiones y las fases están en `docs/PROYECTO_LICITACIONES.md`;
las normas del equipo, en `NORMAS.md`; las decisiones de arquitectura, en `adr/`.

**Estado: fase 1.** Existen los tres binarios con arranque, `/healthz` y parada ordenada, la CI de Go, el **parser de PLACSP** (643, 1044 y 1143),
el **cliente HTTP seguro**, la **lógica de ingesta idempotente** (original como evidencia, versiones y outbox) y el **estado en PostgreSQL**
(vistas, outbox transaccional y puntos de control) con su relay. Todo probado contra las muestras reales de `testdata/`. El **ingestor** ya trabaja de punta a punta: descarga PLACSP cada hora,
guarda los originales en el almacén S3 (RustFS), el estado en su propio Postgres y publica los eventos en NATS JetStream
(`compose.yaml`). El **proyector** consume esos eventos y mantiene el modelo de lectura de los expedientes en Postgres (tabla `expedientes`, con
búsqueda de texto en castellano y catalán). La **API** (`cmd/api`) sirve ese modelo: `GET /api/v1/tenders` (texto, CPV, NUTS, estado, procedimiento,
fuente, importes, fechas, orden y paginación por cursor firmado), `GET /api/v1/tenders/{id}` (ficha con lotes, adjudicaciones y evidencia, con `ETag`)
`GET /api/v1/awards` (adjudicaciones por lote: quién ganó, por cuánto y con qué baja), `GET /api/v1/competitors` (ranking de empresas de un mercado con su cuota), `GET /api/v1/expiring-contracts` (contratos que terminan en un periodo), `GET /api/v1/organizations/{id}` (ficha de comprador o de adjudicatario)
y `GET /api/v1/ops/status`. Exige `Authorization: Bearer <LIC_API_TOKEN>` y no publica ningún puerto; los parámetros del contrato que aún no
existen (`area`, `facetas`, `encaje_min`, `publicada_*`) dan 400 en vez de ignorarse en silencio. La autenticación con Keycloak llegará después.

**Verla desde el Cerebro** (herramienta `licitaciones` de los agentes y sección «Licitaciones» del panel). Con el Cerebro arrancado, une la API del
motor a su red (`licitaciones-api`) y reinicia `api`, `worker` y `panel` para que lean el token:
```bash
docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env up -d
docker compose up -d api worker panel          # el Cerebro usa por defecto LIC_API_TOKEN del mismo .env
```
Los agentes de Licitaciones (Director, Rastreador y Viabilidad) tienen la herramienta; el panel la muestra a quien esté en los grupos `licitaciones`,
`direccion`, `comercial`, `telecom` o `areas` (y a la cuenta de servicio). Los datos del motor siguen en su red interna: el Cerebro solo ve la API.

**Probar la API desde el propio equipo** (publica 127.0.0.1:8090, solo en local):
```bash
docker compose -f licitaciones/compose.yaml -f licitaciones/compose.dev.yaml --env-file .env up -d
TOKEN=$(grep '^LIC_API_TOKEN=' .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8090/api/v1/tenders?q=software&limit=3'
```

**Arrancarlo** (desde la raíz del repositorio; credenciales `LIC_*` en `.env`, ver `.env.example`):
```bash
docker compose -f licitaciones/compose.yaml --env-file .env up -d --build
docker compose -f licitaciones/compose.yaml logs -f ingestor     # «ingesta completada» con las cifras de cada vuelta
```
La carga recorre la cadena de páginas hacia atrás **retomando donde quedó**: una página de archivo ya ingerida se anota (`paginas_ingeridas`) y no se
vuelve a descargar, así que un fallo a mitad de camino (una página lenta) no se paga dos veces. Cada vuelta descarga como mucho `LIC_MAX_PAGINAS` (50)
páginas; si quedan más, la siguiente empieza al minuto (tras un fallo, a los 5 minutos). El histórico más allá de lo que ofrece la sindicación
(ZIP mensuales) se cargará aparte.
Credenciales: de momento el ingestor usa la del almacén y la del bus tal cual (una por servicio, sin las políticas por usuario de SEC-080).

## Estructura
```
cmd/api        API REST (contrato en api/openapi.yaml; hoy: tenders, ficha, adjudicaciones, competidores, contratos que vencen, fichas de organización y estado; internal/api)
cmd/ingestor   servicio de ingesta (internal/ingestor: configuración, cerrojo de líder, planificador y relay)
cmd/proyector  proyector del modelo de lectura (internal/projector); los de grafo y búsqueda llegarán después (ADR 0009)
internal/domain    modelo normalizado (licitación, lotes, resultados, bajas); importes con moneda y significado, sin datos de contacto
internal/connectors/placsp   lector en streaming de las sindicaciones Atom + CODICE: límites de tamaño, sin DTD, fragmento original y SHA-256 por entrada
internal/connectors/fetch   cliente HTTP anti-SSRF: https, lista blanca, IP públicas comprobadas al conectar, redirecciones validadas, tope de tamaño, reintentos
internal/ingest    ingesta de una fuente: página → original (RawStore) → registro normalizado → versión y evento (State); Run recorre las páginas hasta lo ya conocido
internal/storage/pg   estado de la ingesta en PostgreSQL: migraciones, vistas, outbox (Drain con SKIP LOCKED) y puntos de control; usa ingest.Decide
internal/bus       publicador NATS JetStream (flujo LICITACIONES, Nats-Msg-Id = id del evento, espera de PubAck)
internal/storage/s3   originales en un almacén S3 (If-None-Match, Object Lock en el cubo de originales)
internal/projector   evento → original (S3, con comprobación de SHA-256) → parser → tabla `expedientes` (idempotente, solo avanza de versión)
internal/events    relay del outbox: publica en orden, borra solo lo confirmado, reintenta con espera creciente
internal/service   arranque común: registro JSON (slog), entorno, /healthz, parada con SIGINT/SIGTERM
internal/version   versión del binario (se fija al compilar)
bench/grafo    banco de pruebas de la fase 0 (módulo Go aparte)
```

## En local
Hace falta **Go 1.27.3** (el `go.mod` lo declara; con `GOTOOLCHAIN=auto` Go lo descarga solo).
```bash
cd licitaciones
go vet ./...
go tool staticcheck ./...                 # herramientas fijadas en go.mod
go test -race -count=1 ./...
go run ./cmd/api                          # escucha en 127.0.0.1:8081
curl -s localhost:8081/healthz            # {"estado":"ok","servicio":"api","version":"dev"}
```
Las pruebas de PostgreSQL necesitan una base de pruebas (la variable `LICITACIONES_TEST_PG` con la dirección de conexión de una base vacía; sin ella se omiten; cada prueba usa un esquema propio y lo borra).
`golangci-lint` v2.15.0 (la CI usa la misma versión): `go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.15.0 && golangci-lint run`.

## Configuración (variables de entorno)
| Variable | Por defecto | Para qué |
|---|---|---|
| `LICITACIONES_ADDR` | `127.0.0.1:8081` | Dirección de escucha. En contenedor se pone `0.0.0.0:8081` |
| `LICITACIONES_LOG_LEVEL` | `info` | `debug`, `info`, `warn` o `error` |
| `LIC_PG_URL`, `LIC_S3_ENDPOINT`, `LIC_S3_USUARIO`, `LIC_S3_PASSWORD`, `LIC_NATS_URL` | obligatorias | Conexiones del ingestor (`LIC_S3_SEGURO`, `LIC_NATS_USUARIO` y `LIC_NATS_PASSWORD` opcionales) |
| `LIC_FUENTES` | `placsp-643` | `placsp-643`, `placsp-1044`, `placsp-1143`, separadas por comas |
| `LIC_INTERVALO` | `1h` | Entre ingestas de cada fuente (mínimo `5m`: no se castiga a la fuente) |
| `LIC_MAX_PAGINAS` | `50` | Páginas como máximo por ejecución |
| `LIC_TIMEOUT_DESCARGA` | `5m` | Plazo por descarga (entre `30s` y `15m`); PLACSP sirve las páginas despacio |
| `LIC_CONTACTO` | vacío | Correo o web que se anuncia a la fuente en el `User-Agent` |
| `LIC_HISTORICO_DESDE` | vacío | Carga el histórico en ZIP desde esta fecha: `2023` (desde el 1 de enero) o `2023-06`. Vacío = no se carga (ver «Histórico antiguo») |
| `LIC_TIMEOUT_ZIP` | `30m` | Plazo por descarga de un ZIP (entre `1m` y `6h`); si se corta, la siguiente vuelta continúa donde quedó |
| `LIC_HISTORICO_DIR` | carpeta temporal | Dónde se baja el ZIP; en compose es el volumen `historico-tmp` (`/scratch`) |

## Histórico antiguo
La sindicación en vivo solo llega al principio del mes en curso. Lo anterior está en ZIP de datos abiertos de PLACSP: **uno por año cerrado**
(`…Completo3_2025.zip`) y **uno por mes cerrado del año en curso** (`…Completo3_202609.zip`). Con `LIC_HISTORICO_DESDE=2023` el ingestor, después de
cada vuelta de la fuente en vivo (que tiene prioridad), toma **un ZIP pendiente por vuelta**, del más reciente al más antiguo:
1. lo baja al volumen `historico-tmp` (continúa con `Range` una descarga cortada; si el servidor no admite rangos, la repite entera);
2. lo abre sin descomprimirlo en disco y pasa cada `.atom` por **el mismo camino que una página en vivo** (original y página en el almacén, observación
   en el estado, eventos por el outbox). Los límites (SEC-010…013): 64 MiB por `.atom`, 20 000 ficheros, 32 GiB descomprimidos; nada se da por bueno por lo que
   declare el ZIP;
3. anota cada `.atom` ingerido y, al final, el ZIP entero (`paginas_ingeridas`, claves `zip:AAAAMM[/fichero]`): un fallo o un reinicio retoma en el
   siguiente fichero, y un ZIP ya cargado no se vuelve a bajar;
4. borra el ZIP. Un ZIP que aún no existe (404) se salta sin bloquear a los demás y se reintenta en la vuelta siguiente.

Un orden distinto al cronológico no importa: una versión antigua de una licitación no pisa a la nueva (cuenta como `superadas`). El ZIP en sí no se guarda en
`raw` (ADR 0004 lo preveía): cada página y cada entrada que contiene sí, con la misma clave y metadatos que las de la sindicación en vivo, así que la
evidencia es la misma. **POR VERIFICAR** con una descarga real: el servidor exacto de los ZIP (se prueban `contrataciondelsectorpublico.gob.es` y
`contrataciondelestado.es`) y los nombres de los `.atom` de dentro (solo se usa la extensión). Solo `placsp-643`. Mientras no exista el consumidor del
Cerebro, los eventos del histórico van al mismo flujo `LICITACIONES`; cuando exista habrá que llevarlos a `LIC_HISTORICO` (ADR 0002) para que el Cerebro no reciba
millones de «nuevas».

## Reprocesar los expedientes ya cargados
Cuando el parser aprende algo nuevo (por ejemplo, el texto de las prórrogas), los expedientes ya proyectados no lo tienen hasta que se vuelven a leer. No hace falta
volver a descargar nada: `proyector reproyectar` relee de `raw` el original de cada expediente (comprobando su SHA-256), lo interpreta con el parser actual y rehace su
modelo de lectura; las adjudicaciones se recalculan solas. Es una tarea de una sola vez, no un servicio, y se puede repetir o cortar sin riesgo (ADR 0003: el modelo de lectura
es regenerable). Primero simula (no escribe nada) y mira cuántos cambiarían:

```
docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env run --rm proyector reproyectar -simular
docker compose -f licitaciones/compose.yaml -f licitaciones/compose.cerebro.yaml --env-file .env run --rm proyector reproyectar
```

Opciones: `-fuente placsp-643` (solo esa fuente), `-limite N` (como máximo N expedientes) y `-despues ID` (seguir después del último id que enseñó una pasada cortada). Al final dice
cuántos ha **revisado**, **cambiado**, dejado **iguales**, saltado por ser **bajas** (los anulados no se resucitan), **movidos** (llegó una versión nueva mientras tanto: no se pisa) y con
**errores** (el original no se lee o no coincide con su SHA-256: no se proyecta nada de él). No cambia la versión, el original ni la fecha de actualización del expediente.

## Imagen
`docker build -f licitaciones/Dockerfile --build-arg VERSION=$(git rev-parse HEAD) -t licitaciones:local licitaciones`
(una imagen con los tres binarios; `ENTRYPOINT` es `/api`, el resto se elige con `entrypoint`).

## Consumidor de eventos del Cerebro
El Cerebro tiene su propio consumidor del flujo `LICITACIONES` (servicio `licitaciones-eventos` de su `docker-compose.yml`, perfil `licitaciones`). Para que lo
alcance, el bus NATS se une también a la red `cerebro` con `compose.cerebro.yaml` (alias `licitaciones-nats`; sigue pidiendo usuario y clave). Como el evento solo
trae la fuente y el identificador de origen, el consumidor pide el expediente con `GET /api/v1/tenders?fuente=placsp&id_origen=…` (el filtro `id_origen` exige
exactamente una fuente).
