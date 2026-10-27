# ADR 0009 — Modelo de lectura inicial en PostgreSQL (OpenSearch y grafo después)

- **Estado**: Aceptado (provisional hasta cerrar el ADR 0006)
- **Fecha**: 27/10/2026
- **Relacionados**: 0003 (reconstrucción), 0006 (grafo, provisional), §10 fases 1 y 3 del proyecto

## Contexto
El plan (§10) prevé un proyector de grafo (fase 1) y uno de OpenSearch híbrido BM25 + semántico (fase 3). Hoy:
- El ADR 0006 sigue **provisional**: faltan los benchmarks de 1 M de expedientes en hardware estable, y la inclinación es Postgres sin grafo.
- OpenSearch (JVM, memoria alta) no es viable en el PC de desarrollo, que además es inestable; el servidor de producción no existe todavía.
- Hay datos reales ya ingeridos (PLACSP 643) y conviene poder consultarlos cuanto antes para validar el parser y el contrato de la API.

## Decisión
1. Un **proyector de lectura** (`cmd/proyector`) consume los eventos de NATS, lee cada original del almacén comprobando su SHA-256, lo normaliza con el
   parser y lo proyecta en la tabla `expedientes` de la base `licitaciones` (una fila por expediente y fuente, con el registro completo en `documento`).
2. La **búsqueda** de esta primera versión es de PostgreSQL: `tsvector` en castellano y catalán (título y comprador), filtros por CPV, NUTS, estado,
   importes y fechas con índices GIN/B-tree. Sin búsqueda semántica ni facetas pesadas.
3. El proyector es **idempotente y solo avanza de versión**: reentregas y desórdenes no lo estropean; todo el modelo se puede regenerar repitiendo
   los eventos o releyendo `raw` (ADR 0003). Los fallos transitorios (almacén o base caídos) se reintentan con espera creciente; los permanentes
   (original que no coincide con su SHA-256, XML ilegible) se dan por terminados y se registran, sin bloquear al resto.
4. El contrato de la API (`api/openapi.yaml`) **no cambia**: la primera versión implementa un subconjunto (`/tenders`, `/tenders/{id}`, estado del
   motor). Cuando haya OpenSearch o grafo, se añaden como proyectores nuevos sobre los mismos eventos y la API cambia de origen sin cambiar de contrato.

## Consecuencias
- Hay datos consultables ya, sin los servicios pesados; el coste es una búsqueda menos rica (sin semántica) hasta la fase 3.
- La tabla `expedientes` nunca es fuente de verdad. Si cambia el parser, se regenera.
- Pendiente: cola de mensajes muertos visible en el estado del motor (hoy solo queda en el registro), métricas de retraso del consumidor, y
  decidir con datos si OpenSearch compensa frente a Postgres para el volumen real (~7 000 expedientes/mes en 643).
