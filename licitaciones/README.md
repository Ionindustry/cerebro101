# Motor de licitaciones

Código del motor de búsqueda de licitaciones (Go). El proyecto, las decisiones y las fases están en `docs/PROYECTO_LICITACIONES.md`;
las normas del equipo, en `NORMAS.md`; las decisiones de arquitectura, en `adr/`.

**Estado: fase 1.** Existen los tres binarios con arranque, `/healthz` y parada ordenada, la CI de Go, el **parser de PLACSP** (643, 1044 y 1143),
el **cliente HTTP seguro**, la **lógica de ingesta idempotente** (original como evidencia, versiones y outbox) y el **estado en PostgreSQL**
(vistas, outbox transaccional y puntos de control) con su relay. Todo probado contra las muestras reales de `testdata/`. El **ingestor** ya trabaja de punta a punta: descarga PLACSP cada hora,
guarda los originales en el almacén S3 (RustFS), el estado en su propio Postgres y publica los eventos en NATS JetStream
(`compose.yaml`). La API y los proyectores llegan en los PR siguientes.

**Arrancarlo** (desde la raíz del repositorio; credenciales `LIC_*` en `.env`, ver `.env.example`):
```bash
docker compose -f licitaciones/compose.yaml --env-file .env up -d --build
docker compose -f licitaciones/compose.yaml logs -f ingestor     # «ingesta completada» con las cifras de cada vuelta
```
La primera vuelta recorre como mucho `LIC_MAX_PAGINAS` (50) páginas hacia atrás; el histórico anterior se cargará aparte (ZIP mensuales).
Credenciales: de momento el ingestor usa la del almacén y la del bus tal cual (una por servicio, sin las políticas por usuario de SEC-080).

## Estructura
```
cmd/api        API REST (contrato en api/openapi.yaml; endpoints en la fase 3)
cmd/ingestor   servicio de ingesta (internal/ingestor: configuración, cerrojo de líder, planificador y relay)
cmd/proyector  proyectores de grafo y de búsqueda
internal/domain    modelo normalizado (licitación, lotes, resultados, bajas); importes con moneda y significado, sin datos de contacto
internal/connectors/placsp   lector en streaming de las sindicaciones Atom + CODICE: límites de tamaño, sin DTD, fragmento original y SHA-256 por entrada
internal/connectors/fetch   cliente HTTP anti-SSRF: https, lista blanca, IP públicas comprobadas al conectar, redirecciones validadas, tope de tamaño, reintentos
internal/ingest    ingesta de una fuente: página → original (RawStore) → registro normalizado → versión y evento (State); Run recorre las páginas hasta lo ya conocido
internal/storage/pg   estado de la ingesta en PostgreSQL: migraciones, vistas, outbox (Drain con SKIP LOCKED) y puntos de control; usa ingest.Decide
internal/bus       publicador NATS JetStream (flujo LICITACIONES, Nats-Msg-Id = id del evento, espera de PubAck)
internal/storage/s3   originales en un almacén S3 (If-None-Match, Object Lock en el cubo de originales)
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

## Imagen
`docker build -f licitaciones/Dockerfile --build-arg VERSION=$(git rev-parse HEAD) -t licitaciones:local licitaciones`
(una imagen con los tres binarios; `ENTRYPOINT` es `/api`, el resto se elige con `entrypoint`).
