# ADR 0008 — Ubicación del código, módulo Go, imágenes y CI

- **Estado**: Aceptado (la versión exacta de Go se fija al crear `go.mod` en la fase 1)
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor
- **Relacionados**: `docs/CONTRIBUIR.md`, `.github/workflows/ci.yml`, `licitaciones/NORMAS.md`, §12.8 del proyecto

## Contexto
- §1 del proyecto: el código vive en `licitaciones/` dentro de `cerebro101`, con la misma CI y un trabajo de Go nuevo.
- La CI actual (`.github/workflows/ci.yml`) tiene tres trabajos obligatorios para fusionar en `main`
  (`docs/CONTRIBUIR.md`): **API · pruebas de Python**, **Panel · pruebas de Node** y **Configuración · secretos, compose,
  scripts y fichas**. Se lanza en cada PR y en cada `push` a `main`, `permissions: contents: read`, cancela ejecuciones
  repetidas por rama y usa acciones por etiqueta (`actions/checkout@v4`…).
- `NORMAS.md`: Go estable actual; `go vet`, `staticcheck`, `gofmt` sin avisos; `golangci-lint` en CI; pruebas con `-race`;
  dependencias mínimas y fijadas.
- No hay `go` instalado en el equipo de desarrollo actual (comprobado): la CI es la referencia hasta que se instale.

## Opciones
| Criterio | A. Carpeta `licitaciones/` en el monorepo | B. Repositorio aparte |
|---|---|---|
| Un PR puede cambiar contrato (OpenAPI/eventos) y consumidor (herramienta Python, panel) a la vez | Sí | No (dos PR coordinados) |
| La búsqueda de secretos y las reglas de `main` se aplican sin configurar nada | Sí | Hay que duplicarlas |
| Tiempo de CI añadido a PR que no tocan Go | ~2–4 min en paralelo (a medir) | 0 |
| Versionado y despliegue independientes | Por etiqueta de imagen | Natural |

## Decisión
**A.** Además:

### Módulo y versión de Go
- `licitaciones/go.mod` con módulo **`github.com/ionindustry/cerebro101/licitaciones`** (ruta del remoto `origin`).
- Versión: la **última estable** al crear `go.mod` (a 26/10/2026 debería ser la 1.27.x; **POR VERIFICAR** en
  `go.dev/dl`), escrita en la directiva `go` y con `toolchain` fijado al parche. Mínimo 1.24 (directivas `tool`).
  Política: se sube a la nueva versión mayor en los 2 meses siguientes a su salida (Go mantiene las dos últimas).
- Herramientas fijadas en `go.mod` con directivas `tool` (`honnef.co/go/tools/cmd/staticcheck`,
  `golang.org/x/vuln/cmd/govulncheck`) y ejecutadas con `go tool …`: misma versión en local y en CI.
  `golangci-lint` v2 se ejecuta con su acción oficial y versión fijada (su documentación desaconseja `go tool` para él).
- Configuración en `licitaciones/.golangci.yml` (v2): `govet`, `staticcheck`, `errcheck`, `ineffassign`, `unused`,
  `gosec`, `bodyclose`, `noctx`, `errorlint`, `contextcheck`, `sqlclosecheck`, `rowserrcheck`; formateadores `gofmt` y
  `goimports`. Sin `//nolint` sin motivo escrito.

### Estructura (§12.8 + dos añadidos justificados)
```
licitaciones/
  cmd/api/            API REST (chi), autenticación, autorización, límites
  cmd/ingestor/       conectores, planificador con cerrojo de líder, outbox + relay
  cmd/proyector/      NUEVO: proyectores de grafo y de búsqueda, reconstrucción, DLQ (subcomandos)
  internal/connectors internal/domain internal/graph internal/search internal/storage
  internal/events internal/scoring internal/simulation
  internal/auth       NUEVO: validación JWT y matriz de permisos (ADR 0007)
  api/openapi.yaml  api/eventos.md
```
`cmd/proyector` separado del ingestor porque el ingestor es el único con salida a internet: si se compromete un parser,
no debe tener credenciales de escritura en el grafo ni en OpenSearch (ADR 0004, mínimo privilegio), y así cada uno tiene
sus límites de memoria. `internal/auth` porque la autorización se comprueba en cada *handler* y debe tener pruebas propias.

### Dependencias previstas (cada una se justifica en su PR: licencia, mantenimiento)
`go-chi/chi/v5`, `jackc/pgx/v5`, `nats-io/nats.go`, `aws/aws-sdk-go-v2` (S3), `opensearch-project/opensearch-go`,
`neo4j/neo4j-go-driver` (Bolt, sirve para Neo4j y Memgraph), `redis/go-redis/v9`, `coreos/go-oidc/v3`, OpenTelemetry.
Biblioteca estándar para registro (`log/slog`), configuración (variables de entorno) y XML (`encoding/xml` en *streaming*).
Pruebas de integración con contenedores efímeros (`testcontainers-go`, POR VERIFICAR frente a `services:` de Actions).
Validación del contrato: OpenAPI **3.1**; los generadores de Go más usados solo cubren bien la 3.0, así que **no se genera
código**: los *handlers* se escriben a mano y una prueba de contrato valida las respuestas contra `api/openapi.yaml`
(`pb33f/libopenapi-validator`, que admite 3.1; POR VERIFICAR en la fase 3).

### Imágenes
- Un `licitaciones/Dockerfile` multietapa: compilación en `golang:<versión>-bookworm` fijada por *digest*,
  `CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X …version=<sha>"`; ejecución en
  `gcr.io/distroless/static-debian12:nonroot` (sin shell, usuario 65532).
- **Una imagen** con los tres binarios (`/api`, `/ingestor`, `/proyector`); cada servicio del compose elige el comando.
  Etiqueta = SHA del commit. Contenedores con `read_only: true`, `cap_drop: [ALL]`, límites de memoria y CPU.
- Compose del motor en **`licitaciones/compose.yaml`** (proyecto `licitaciones`), con la red `cerebro` como externa:
  se arranca y para sin tocar el Cerebro. No se modifica el `docker-compose.yml` del Cerebro salvo para lo de ADR 0007
  (fase 4).

### Trabajo de CI nuevo (fragmento propuesto; **no se aplica todavía**)
Se añade en el mismo PR que crea `licitaciones/go.mod` (fase 1); antes, el trabajo fallaría por no haber módulo.
Va como trabajo independiente: no cambia ni ralentiza los tres existentes (corren en paralelo).

```yaml
  licitaciones:
    name: Licitaciones · Go
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    defaults:
      run:
        working-directory: licitaciones
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version-file: licitaciones/go.mod
          cache-dependency-path: licitaciones/go.sum
      - name: go.mod y go.sum ordenados
        run: go mod tidy -diff
      - name: Formato (gofmt)
        run: test -z "$(gofmt -l .)" || { gofmt -l .; exit 1; }
      - name: go vet
        run: go vet ./...
      - name: staticcheck
        run: go tool staticcheck ./...
      - name: golangci-lint
        uses: golangci/golangci-lint-action@v8     # POR VERIFICAR la versión vigente de la acción
        with:
          version: v2.5.0                          # fijada; POR VERIFICAR la última v2 al crear el trabajo
          working-directory: licitaciones
      - name: Pruebas (detector de carreras, sin caché)
        run: go test -race -count=1 -timeout 10m ./...
      - name: Vulnerabilidades conocidas (govulncheck)
        run: go tool govulncheck ./...
      - name: Imagen (solo construir, sin publicar)
        working-directory: .
        run: docker build -f licitaciones/Dockerfile -t licitaciones:ci licitaciones
```
Además, en el trabajo **Configuración** existente se añadirá una línea cuando exista el compose del motor:
`docker compose -f licitaciones/compose.yaml --env-file .env.example config -q`.

Las pruebas de integración (NATS, MinIO, OpenSearch, grafo en contenedores efímeros) van en un segundo trabajo
`licitaciones-integracion` (`go test -tags=integration`) que empieza como **no obligatorio** hasta que sea estable
(< 1 % de fallos espurios en 2 semanas) y su duración sea < 10 min.

«Licitaciones · Go» pasa a ser **comprobación obligatoria** de `main` (regla de GitHub, `docs/CONTRIBUIR.md`) cuando lleve
una semana en verde.

## Consecuencias
- Todos los PR pagan unos minutos más de CI en paralelo (a medir; si supera 5 min de mediana en PR que no tocan
  `licitaciones/`, se añade un filtro de rutas que deje la comprobación en verde sin ejecutarse).
- El detector de secretos (`scripts/comprobar_secretos.py`) cubre ya `licitaciones/` sin cambios.
- Hay que actualizar `docs/CONTRIBUIR.md` (comprobaciones obligatorias y cómo ejecutar Go en local) en el PR de la fase 1.

## Cómo se revisará
Fin de la fase 1: duración real del trabajo, falsos positivos de `golangci-lint` (si > 5 supresiones, se revisa la
lista de *linters*) y estado de la validación de contrato 3.1.
