# ADR 0003 — Consistencia y recuperación: S3 como evidencia, proyecciones reconstruibles y outbox

- **Estado**: Aceptado (RPO/RTO **propuestos**; se confirman con el ensayo de restauración de la fase 6)
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor
- **Relacionados**: 0002 (NATS), 0004 (MinIO), 0006 (grafo), `api/eventos.md`

## Contexto
- §12.6: el S3 conserva la evidencia; el grafo y OpenSearch son **proyecciones reconstruibles** desde S3 y el log.
- `NORMAS.md`: idempotencia por (fuente, id de origen, hash); repetir una ingesta no duplica; original inmutable con
  SHA-256, URL, fecha de captura, versión del parser y licencia.
- La ingesta escribe en tres sitios (S3, Postgres, NATS). Escribir en varios sistemas sin coordinación (*dual write*) pierde
  o duplica eventos cuando el proceso cae entre dos escrituras.
- Para clasificar un cambio como `licitacion.nueva` o `.modificada` el ingestor necesita recordar qué ha visto: ese estado
  vive en Postgres (`licitaciones`), igual que `ingestion_runs` y los puntos de control (§1 del proyecto).

## Opciones

### Cómo publicar los eventos sin perderlos ni inventarlos
| Opción | Pérdida de eventos si el proceso cae | Eventos «fantasma» | Coste |
|---|---|---|---|
| A. Publicar en NATS y luego actualizar Postgres (punto de control) | No (se repite la página) | Sí: si cae tras publicar, al repetir puede emitir `nueva` dos veces fuera de la ventana de duplicados | Mínimo |
| B. Actualizar Postgres y luego publicar | **Sí**: si cae entre medias, el estado dice «visto» y el evento no sale nunca | No | Mínimo |
| C. **Outbox transaccional** en Postgres: estado + evento en la misma transacción; un *relay* publica en NATS | No | No | Una tabla y un *relay* (~200 líneas con pruebas) |
| D. S3 como único log (los proyectores leen S3 por listado) | No | No | Listar S3 cada pocos segundos; sin control de flujo ni *dead-letter*; acopla proyectores a la disposición de claves |

Criterios: cero eventos perdidos y cero duplicados semánticos en la prueba de «matar el ingestor en cada paso» (fase 1).

### Cómo reconstruir una proyección
| Opción | Tiempo (5 M versiones) | Riesgo |
|---|---|---|
| E. Reproducir todo el log de NATS | Necesita retención infinita del log (≈ 15–20 GB y creciendo) | El log se convierte en una segunda fuente de verdad |
| F. **Recarga masiva desde `processed`/`raw` en S3 + puesta al día desde NATS** | Objetivo < 8 h (a medir) | Ninguno nuevo: S3 ya es la verdad |

## Decisión
**C (outbox) + F (reconstrucción desde S3).**

### Fuentes de verdad
| Dato | Dónde | Naturaleza |
|---|---|---|
| Original descargado, byte a byte, con SHA-256 | MinIO `raw` (Object Lock, ADR 0004) | **Evidencia**: inmutable, nunca se reescribe |
| Registro normalizado por versión de parser | MinIO `processed` | Derivado de `raw` (regenerable con el parser) |
| Estado de ingesta: `vistas(fuente, id_origen) → ultima_version, ultimo_hash, clave_s3`, puntos de control, `ingestion_runs`, `outbox` | Postgres `licitaciones` | Operativo (las `vistas` se pueden regenerar listando `processed`) |
| Alertas, entregas, simulaciones guardadas, usuarios de alertas | Postgres `licitaciones` | **Transaccional** (no reconstruible: copia de seguridad) |
| Grafo, índices `tenders`/`awards`, caché Redis | Neo4j/Memgraph, OpenSearch, Redis | **Proyecciones**: se pueden borrar y reconstruir |

### Secuencia de la ingesta (por entrada)
1. Descargar con límites; calcular `sha256` de los bytes del original.
2. `PUT raw/...{sha256}.xml` con `If-None-Match: *` (si existe, es la misma evidencia: seguir). Metadatos: URL, fecha de
   captura, ETag de origen, licencia.
3. Parsear (versión de parser `vN`) → registro normalizado → `hash_normalizado` (SHA-256 del JSON canónico sin metadatos de
   captura). `PUT processed/...` (idempotente por clave).
4. **Una transacción en Postgres**: leer `vistas(fuente, id_origen)`;
   - mismo `hash_normalizado` → nada (repetir no duplica);
   - no existe → `version_entidad = 1`, evento `licitacion.nueva` (o el tipo que corresponda al anuncio);
   - distinto → `version_entidad + 1`, evento `.modificada` / `.adjudicada` / `.formalizada` / `.anulada`;
   - `INSERT` en `outbox` (id del evento determinista, sujeto, cuerpo) y avance del punto de control de la fuente.
5. *Relay* (goroutine del ingestor): `SELECT … FOR UPDATE SKIP LOCKED LIMIT 500`, publica con `Nats-Msg-Id = id`, espera
   los `PubAck` y borra las filas confirmadas. Si NATS no está, reintenta con espera creciente; el outbox crece en Postgres
   (métrica y alerta si > 10 000 filas o la más antigua > 15 min).

Si cae entre 2 y 4: queda un objeto en S3 sin evento (inofensivo; el siguiente ciclo lo reencuentra). Si cae entre 4 y 5:
el evento está en el outbox y sale al rearrancar. Si cae tras publicar y antes de borrar: se republica con el mismo id
(NATS lo descarta en la ventana de 2 h; fuera de ella, el consumidor lo descarta por versión).

### Consumidores idempotentes
Clave lógica: **(fuente, id_origen, hash_normalizado)**; orden: **`version_entidad`** (monótona por entidad, la asigna el
ingestor, que es el único escritor gracias al cerrojo de líder).
- **OpenSearch**: `index` con `version_type=external` y `version = version_entidad`. Una versión igual o menor devuelve
  409, que el proyector trata como «ya aplicado» (no como error). Protege también contra el desorden de las reentregas.
- **Grafo**: `MERGE` por (fuente, id_origen); las propiedades del nodo actual se escriben solo
  `WHERE coalesce(n.version_entidad, 0) < $v`; cada `NoticeVersion` se crea con `MERGE` por (fuente, id_origen, hash):
  repetir no crea duplicados. Escrituras en lotes (`UNWIND`, 500–1 000).
- **Cerebro** (`cerebro-embudo`): `INSERT … ON CONFLICT (motor_id) DO UPDATE … WHERE version < EXCLUDED.version` en su
  tabla `licitaciones` (ADR 0007).
- **Alertas**: tabla `entregas(alerta_id, evento_id)` con clave única: una alerta no se envía dos veces.

### Reconstrucción y reindexado completo (`proyector reconstruir --destino busqueda|grafo`)
1. Anotar la última secuencia del stream `LICITACIONES` (S₀).
2. Crear el destino nuevo vacío: índice `tenders-AAAAMMDD-hhmm` (alias `tenders` sin tocar) o base de grafo nueva.
3. Recorrer `processed/` (o reparsear `raw/` si cambia el parser) en paralelo por fuente y mes, escribiendo en lotes
   (`bulk` / `UNWIND`) con las mismas reglas de versión. Memoria constante (*streaming*), *workers* acotados.
4. Ponerse al día desde S₀ con un consumidor efímero (ADR 0002). Las versiones repetidas se descartan solas.
5. Validar: recuento por fuente frente a `vistas`, y muestra aleatoria de 1 000 ids con `hash_normalizado` igual.
6. Cambio atómico de alias (OpenSearch) o de la cadena de conexión (grafo); se conserva el anterior 48 h para volver atrás.
7. Incrementar la generación de caché (ADR 0005).

**Reconciliación semanal** (§3 del proyecto): compara `vistas` (versión y hash por entidad) con cada proyección y
reproyecta las diferencias. Cubre también la pérdida del volumen de NATS.

### Copias de seguridad y RPO/RTO propuestos
| Componente | Copia | RPO propuesto | RTO propuesto |
|---|---|---|---|
| MinIO `raw` (evidencia) | Réplica diaria fuera del servidor (`mc mirror` a destino externo, cifrada); Object Lock en local | Local 0 (se escribe antes de emitir); desastre del servidor ≤ **24 h** (y lo publicado sigue en las fuentes: se puede volver a descargar, salvo versiones intermedias) | ≤ 4 h (copia de vuelta) |
| MinIO `processed` | No se copia (se regenera desde `raw`) | — | Regeneración: ≤ 8 h (a medir) |
| Postgres `licitaciones` | `pg_dump` nocturno, añadido a `scripts/copia_seguridad.sh` | ≤ **24 h** (alertas y simulaciones). Revisar si se exige menos | ≤ 1 h |
| OpenSearch | *Snapshot* diario al bucket `snapshots` de MinIO (+ réplica externa) | 24 h, pero se pone al día desde NATS (30 días): efectivo ≈ **0** | Restaurar *snapshot* ≤ **1 h**; reconstrucción completa ≤ **8 h** |
| Grafo | Volcado/instantánea diaria (mecanismo según el motor elegido, ADR 0006) | Igual que OpenSearch: efectivo ≈ 0 | Restaurar ≤ 1 h; reconstrucción ≤ 8 h |
| NATS | Volumen en disco; sin copia | Lo no consumido sale de la reconciliación | Recrear streams (código) < 5 min |
| Redis | Ninguna (caché) | — | Arranque en frío |

La disponibilidad de lectura del 99,9 % mensual (§9) deja ≈ 43 min/mes: la recuperación normal es **restaurar** la
*snapshot* y ponerse al día, no reconstruir. Con un único servidor, el 99,9 % es una hipótesis que depende del hardware.

## Consecuencias
- Postgres `licitaciones` es pieza crítica de la ingesta (si cae, la ingesta para; las lecturas no). Usa el servidor de
  Postgres existente con base y roles propios (`lic_ingestor`, `lic_api`, `lic_migraciones`).
- Las proyecciones nunca son la única copia de nada: se pueden borrar sin perder datos (excepto el tiempo de reconstrucción).
- Hay que versionar los parsers y guardar `version_parser` en `processed` y en los eventos.
- Un reproceso con parser nuevo publica en `lichist.v1.…` (ADR 0002), no en vivo: el Cerebro no recibe falsos «modificada».
- Pruebas obligatorias en la fase 1: matar el ingestor tras cada paso (2, 3, 4, 5) y comprobar 0 pérdidas y 0 duplicados;
  reindexado completo sobre el corpus de `testdata`.

## Cómo se revisará
- Fase 1: medir el tiempo de reconstrucción con el histórico real y el crecimiento del outbox en la carga histórica.
- Fase 6: ensayo de restauración completo (borrar OpenSearch y grafo, restaurar, poner al día) cronometrado; los RPO/RTO
  pasan de propuestos a comprometidos o se corrige este ADR.
- Reabrir si la reconstrucción completa supera 24 h o el outbox se convierte en cuello de botella (> 5 min de retraso
  sostenido en la carga histórica).
