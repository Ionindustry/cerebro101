# Motor de licitaciones

Código del motor de búsqueda de licitaciones (Go). El proyecto, las decisiones y las fases están en `docs/PROYECTO_LICITACIONES.md`;
las normas del equipo, en `NORMAS.md`; las decisiones de arquitectura, en `adr/`.

**Estado: fase 1.** Existen los tres binarios con arranque, `/healthz` y parada ordenada, la CI de Go, el **parser de PLACSP** (643, 1044 y 1143),
el **cliente HTTP seguro**, la **lógica de ingesta idempotente** (original como evidencia, versiones y outbox) y el **estado en PostgreSQL**
(vistas, outbox transaccional y puntos de control) con su relay. Todo probado contra las muestras reales de `testdata/`. Almacén S3 (RustFS), NATS, el planificador,
la API y los proyectores llegan en los PR siguientes.

## Estructura
```
cmd/api        API REST (contrato en api/openapi.yaml; endpoints en la fase 3)
cmd/ingestor   conectores y planificador de la ingesta
cmd/proyector  proyectores de grafo y de búsqueda
internal/domain    modelo normalizado (licitación, lotes, resultados, bajas); importes con moneda y significado, sin datos de contacto
internal/connectors/placsp   lector en streaming de las sindicaciones Atom + CODICE: límites de tamaño, sin DTD, fragmento original y SHA-256 por entrada
internal/connectors/fetch   cliente HTTP anti-SSRF: https, lista blanca, IP públicas comprobadas al conectar, redirecciones validadas, tope de tamaño, reintentos
internal/ingest    ingesta de una fuente: página → original (RawStore) → registro normalizado → versión y evento (State); Run recorre las páginas hasta lo ya conocido
internal/storage/pg   estado de la ingesta en PostgreSQL: migraciones, vistas, outbox (Drain con SKIP LOCKED) y puntos de control; usa ingest.Decide
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

## Imagen
`docker build -f licitaciones/Dockerfile --build-arg VERSION=$(git rev-parse HEAD) -t licitaciones:local licitaciones`
(una imagen con los tres binarios; `ENTRYPOINT` es `/api`, el resto se elige con `command`).
