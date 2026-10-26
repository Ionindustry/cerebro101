# ADR 0006 — Base de datos de grafos

- **Estado**: **PROVISIONAL**
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor, con los datos del banco de pruebas
- **Relacionados**: 0003 (reconstrucción), §4, §5, §6 y §12.3/§12.7 del proyecto; banco de pruebas en
  `licitaciones/bench/grafo` con resultados en `licitaciones/docs/BENCH_GRAFO.md` (lo hace otro miembro del equipo)

## Contexto
- §12.3: el grafo guarda relaciones e historial: `Procedure`, `Notice`, `NoticeVersion`, `Lot`, `Organization`, `Award`,
  `Contract`, `CPV`, `Document`, `Source` (+ `LOCATED_IN`, `COMPETED_IN`).
- Consultas que justifican el grafo (1–2 saltos): competidores de un CPV en una zona, a quién adjudica un organismo, contra
  quién se compite, competidores probables del simulador (§6).
- SLO: vecindad del grafo (1–2 saltos) p95 < 50 ms. El grafo **no** está en la ruta de búsqueda ni de la ficha.
- Corpus del banco: sintético de 1 M expedientes y 5 M anuncios/versiones (§10, fase 0).
- Memoria compartida: 62 GB con el Cerebro y Ollama. Presupuesto propuesto para el grafo: **≤ 10 GB** de límite de
  contenedor (ver presupuesto en `licitaciones/README.md`).
- Es una **proyección** (ADR 0003): se puede reconstruir; la durabilidad propia importa para el RTO, no para no perder datos.

## Opciones
| Opción | Notas conocidas (a confirmar con el banco) |
|---|---|
| A. **Neo4j Community** | Disco + caché de páginas (montón JVM + *page cache* configurables); sin clúster ni copias en caliente en Community (volcado con la base parada, POR VERIFICAR en la versión actual); licencia GPLv3 |
| B. **Memgraph Community** | En memoria (todo el grafo en RAM) con instantáneas y WAL en disco; licencia BSL 1.1 (uso interno permitido, POR VERIFICAR texto vigente); protocolo Bolt y Cypher |
| C. **Sin base de grafos**: tablas en Postgres + agregaciones en OpenSearch (`awards`) | Una pieza menos; las consultas de 1–2 saltos son *joins* sencillos. Se evalúa como **control**: si cumple los criterios, la complejidad del grafo no se justifica (principio del arquitecto) |

Ambos motores de grafo se usan con el mismo controlador Go (`neo4j-go-driver`, Bolt) y Cypher; el código de
`internal/graph` se escribe contra una interfaz propia para no depender de extensiones de ninguno.

## Criterios (medibles en el banco; los publica `docs/BENCH_GRAFO.md`)
| # | Criterio | Umbral para aceptar |
|---|---|---|
| 1 | Vecindad 1–2 saltos (5 consultas tipo de §5: competidores por CPV+NUTS, adjudicatarios de un organismo, rivales de un proveedor, competidores probables del simulador, historial de un expediente) — p50/p95/p99 con caché caliente | **p95 < 50 ms**, p99 < 150 ms, a 20 consultas/s concurrentes |
| 2 | Las mismas con caché fría (tras reinicio) | p95 < 200 ms; tiempo hasta caliente < 5 min |
| 3 | RAM con el corpus de 1 M / 5 M (RSS máximo) | ≤ **10 GB** (con margen para 5 años de crecimiento × 1,5) |
| 4 | CPU durante 1 y la ingesta | sin saturar más de 4 núcleos |
| 5 | Ingesta por lotes (`UNWIND` 500–1 000, idempotente por versión) | ≥ **2 000 entidades/s** (5 M en < 45 min) |
| 6 | Reconstrucción completa desde `processed` | < **8 h** (RTO de ADR 0003) |
| 7 | Recuperación tras matar el proceso (`kill -9`) | arranque y datos consistentes en < 15 min; pérdida ≤ lo no confirmado |
| 8 | Copia en caliente / restauración | restaurar en < 1 h; indicar si exige parar el servicio |
| 9 | Disco | GB con el corpus; crecimiento por millón de versiones |
| 10 | Licencia y mantenimiento | uso interno sin coste permitido; versión con soporte y parches; imagen oficial fijable por *digest* |
| 11 | Alta disponibilidad (informativo, §12 «HA y recuperación») | qué edición la permite y a qué coste; no bloquea (un solo servidor) |

Reglas del banco: mismos datos, mismo hardware, límites de memoria y CPU fijados en los contenedores, consultas
parametrizadas, 3 repeticiones, resultados y *scripts* reproducibles en `licitaciones/bench/grafo`.

## Estructura del modelo (común a cualquier elección)
- Identidad: cada nodo tiene `uid` (UUID interno) y, cuando aplica, `(fuente, id_origen)`; `Organization` se identifica
  por `nif` o `dir3` (**nunca por nombre**); restricciones de unicidad sobre esas claves.
- `NoticeVersion` guarda `hash_normalizado`, `version_entidad`, `clave_raw`, `sha256`, `url_origen`, `capturado_en`,
  `version_parser` (la evidencia del historial, ADR 0003).
- `AWARDED_TO` lleva importe (con moneda, impuestos y significado), baja y fecha; `COMPETED_IN` solo desde actas.
- Índices: claves de identidad, `CPV.codigo`, `Organization.nif`, `Organization.dir3`, `Lot.nuts`.
- El esquema exacto (propiedades y tipos) lo fija el especialista de grafo (`.claude/agents/licitaciones-grafo.md`) en la
  fase 1, a partir del corpus real.

## Decisión
**Decisión: pendiente del banco de pruebas (licitaciones/docs/BENCH_GRAFO.md).**

Regla de decisión, fijada de antemano para no elegir por preferencia:
1. Se descarta la opción que no cumpla los criterios 1, 3, 5, 6 o 10.
2. Si C (sin grafo) cumple 1 y 5 con el mismo corpus, se elige C (menos piezas).
3. Entre las que cumplan, gana la de menor RAM (3) salvo que la otra mejore el p95 (1) en más de un 30 %.
4. Empate: la de copia en caliente (8) más sencilla.

## Consecuencias (las que no dependen del resultado)
- La fase 1 puede empezar sin esta decisión: el proyector de grafo se escribe contra la interfaz de `internal/graph` con
  Bolt/Cypher y pruebas de integración contra el motor elegido en cuanto exista; ingesta, S3, NATS y OpenSearch no dependen
  de ella.
- Cualquiera que sea la elección, el grafo lleva límites de memoria en el contenedor y queda fuera de la ruta de búsqueda.
- Si se elige Memgraph, la RAM del grafo crece con los datos: alerta al 80 % del límite y plan de servidor aparte (§13).

## Cómo se revisará
- Al publicarse `docs/BENCH_GRAFO.md`: se aplica la regla de decisión, se cambia el estado a Aceptado y se escribe la
  elección con las cifras.
- Después, al cumplir 5 años de histórico cargados (fase 1) se vuelve a medir el criterio 1 y 3 con datos reales.
