# ADR 0002 — Mensajería: NATS JetStream

- **Estado**: Aceptado (los límites numéricos son de partida y se ajustan con las métricas de la fase 1)
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor
- **Relacionados**: 0003 (consistencia), 0007 (consumidor del Cerebro), `api/eventos.md` (esquemas)

## Contexto
- §12.6 del documento y §1 del proyecto: entrega al menos una vez, *dead-letter* y **reproducción del log** para reconstruir
  proyecciones (grafo, OpenSearch).
- Un único servidor (62 GB de RAM compartidos con el Cerebro y Ollama). Sin alta disponibilidad multinodo.
- Lección del atasco de octubre de 2026 en el Cerebro: 1,1 millones de tareas encoladas en Redis sin que nadie lo viera
  (§7.8 del proyecto). Toda cola tiene límites, caducidad y métricas de retraso.
- Volumen esperado (POR VERIFICAR con el corpus de `licitaciones/testdata` y `docs/FUENTES.md`):
  - en vivo: del orden de **3 000–10 000 eventos/día** (PLACSP 643 y 1044 cada hora, TED diario), picos < 50 msg/s;
  - carga histórica de 5 años: del orden de **5 millones** de eventos, una vez, a ≥ 1 000 msg/s para acabar en horas;
  - tamaño de evento: 1–4 KB (lleva referencias a S3, no el documento).
- Productores y consumidores: ingestor y proyectores en Go; consumidor del Cerebro en Python.

## Opciones

| Criterio (medible) | A. NATS JetStream | B. Kafka (KRaft, 1 nodo) | C. Redis Streams |
|---|---|---|---|
| RAM en reposo con nuestro volumen | decenas de MB (binario Go; **a medir** en fase 1, objetivo < 256 MB) | JVM: ≥ 1 GB de montón recomendado + caché de páginas | todo el log en RAM: 5 M × ~3 KB ≈ 15 GB en la carga histórica |
| Piezas que operar | 1 binario, 1 volumen | 1 JVM (KRaft) + herramientas de administración | ya existe, pero habría que separarlo del Redis del Cerebro |
| Deduplicación en el broker | **Sí**: cabecera `Nats-Msg-Id` con ventana configurable | Productor idempotente (solo reintentos de la misma sesión, no por clave de negocio) | No |
| *Dead-letter* | No nativo; avisos `MAX_DELIVERIES`/`MSG_TERMINATED` + stream DLQ propio | No nativo (patrón de tema DLQ) | No nativo (`XPENDING`/`XCLAIM` a mano) |
| Límite de mensajes en vuelo por consumidor | **`MaxAckPending`** | `max.poll.records` + gestión manual | No |
| Reintentos con espera creciente | **`BackOff`** por consumidor | A mano | A mano |
| Reproducción desde una secuencia/fecha | Sí (`DeliverPolicy` por secuencia o por fecha) | Sí (offsets) | Sí (por id) |
| Persistencia | Ficheros, `MaxAge`/`MaxBytes` | Ficheros, retención por tiempo/tamaño, compactación | AOF/RDB; limitado por RAM |
| Cliente Go / Python | `nats.go/jetstream` / `nats-py` (oficiales) | `franz-go` / `confluent-kafka` (librdkafka, C) | `go-redis` / `redis-py` |
| Rendimiento necesario (≥ 1 000 msg/s, 1 nodo) | Sobrado | Sobrado | Sobrado |

## Decisión
**A. NATS JetStream**, un único servidor `nats` (imagen oficial fijada por versión y *digest*), almacenamiento en fichero,
réplicas = 1. Gana en los criterios que nos importan: memoria, una pieza, deduplicación en el broker y control de flujo
(`MaxAckPending`, `BackOff`) sin código propio. Kafka aporta compactación y ecosistema que no necesitamos y cuesta ≥ 1 GB de
JVM. Redis Streams obliga a tener el log en RAM y a construir a mano deduplicación, *dead-letter* y control de flujo:
justo lo que falló en octubre.

### Configuración del servidor
- `jetstream { store_dir: /data, max_memory_store: 64MB, max_file_store: 20GB }`; contenedor con límite de **512 MB** de RAM.
- Autenticación por usuario y contraseña **por servicio** con permisos de sujeto (mínimo privilegio, ver «Permisos»).
- Monitorización HTTP (`:8222`) solo en la red interna, para las métricas de retraso.

### Streams
| Stream | Sujetos | Retención | Límites | Uso |
|---|---|---|---|---|
| `LICITACIONES` | `lic.v1.>` | `limits`, `discard: old` | `MaxAge` **30 días**, `MaxBytes` 8 GiB, `MaxMsgSize` 64 KiB, `Duplicates` **2 h**, `DenyDelete`, `DenyPurge` | Eventos de dominio **en vivo** y `ingesta.ejecutada` |
| `LIC_HISTORICO` | `lichist.v1.>` | `limits` | `MaxAge` **7 días**, `MaxBytes` 12 GiB, `MaxMsgSize` 64 KiB, `Duplicates` 2 h | Carga histórica y reprocesos (nuevo parser). **Solo los proyectores** lo consumen: el Cerebro nunca recibe 5 M «nuevas» |
| `LIC_DLQ` | `lic.dlq.>` | `limits` | `MaxAge` **30 días**, `MaxBytes` 1 GiB | Mensajes que agotaron reintentos o se descartaron por inválidos |

Ventana de duplicados de 2 h (no 24 h): cubre los reintentos del *relay* del outbox (ADR 0003) sin tener millones de ids en
memoria durante la carga histórica; fuera de la ventana protege la idempotencia de los consumidores.

### Sujetos
`lic.v1.<entidad>.<accion>.<fuente>` — p. ej. `lic.v1.licitacion.nueva.placsp`, `lic.v1.licitacion.adjudicada.ted`,
`lic.v1.ingesta.ejecutada.placsp`. Fuentes: `placsp` (643), `placsp_agregadas` (1044), `ted`, `cat` (Transparència),
`placsp_menores` (si se confirma). La versión mayor del esquema va en el sujeto (`v1`); un cambio incompatible publica en
`lic.v2.…` en paralelo durante al menos una fase (ver `api/eventos.md`). El histórico usa los mismos tokens con `lichist.v1.…`.

### Consumidores (todos *durable*, *pull*, `AckPolicy: explicit`)
| Consumidor | Stream · filtro | `AckWait` | `MaxDeliver` | `BackOff` | `MaxAckPending` | Lote |
|---|---|---|---|---|---|---|
| `proy-grafo` | `LICITACIONES` · `lic.v1.licitacion.>` | 60 s | 8 | 5 s, 30 s, 2 min, 10 min, 30 min, 1 h, 2 h | 2 000 | 500 |
| `proy-busqueda` | `LICITACIONES` · `lic.v1.licitacion.>` | 60 s | 8 | igual | 2 000 | 500 |
| `proy-grafo-hist`, `proy-busqueda-hist` | `LIC_HISTORICO` · `lichist.v1.>` | 120 s | 8 | igual | 5 000 | 1 000 |
| `alertas` (en `cmd/api` o `cmd/proyector`) | `LICITACIONES` · `lic.v1.licitacion.>` | 30 s | 6 | 5 s, 30 s, 2 min, 10 min, 30 min | 500 | 100 |
| `cerebro-embudo` (Python, ADR 0007) | `LICITACIONES` · `lic.v1.licitacion.nueva.>`, `…adjudicada.>`, `…anulada.>` | 120 s | 6 | 10 s, 1 min, 5 min, 30 min, 2 h | **100** | 20 |
| `ops` (panel operativo) | `LICITACIONES` · `lic.v1.ingesta.>` | 30 s | 5 | — | 50 | 10 |

Varios filtros en un consumidor (`FilterSubjects`) requieren NATS ≥ 2.10; si el cliente `nats-py` elegido no los admite
(POR VERIFICAR en la fase 4), `cerebro-embudo` filtra `lic.v1.licitacion.>` y confirma sin actuar los tipos que no usa.

`MaxAckPending` limita el trabajo en vuelo: si un consumidor se atasca, el broker deja de entregarle y el retraso **crece en
el stream** (que tiene tope y caducidad), no en la memoria de nadie. Reconsumir es seguro porque los consumidores son
idempotentes (ADR 0003).

### Caducidad
- Del log: `MaxAge` por stream (30 / 7 / 30 días). Un consumidor parado más de 30 días se recupera reconstruyendo desde S3
  (ADR 0003), no desde NATS.
- De la relevancia: el consumidor del Cerebro confirma (*ack*) sin actuar los eventos `licitacion.nueva` cuyo plazo de
  presentación ya ha pasado o con `ocurrido_en` de hace más de 72 h, y lo cuenta en una métrica.
- Consumidores efímeros de reproducción: `InactiveThreshold` 1 h, para que no queden olvidados.

### *Dead-letter*
NATS no tiene DLQ nativa. Se hace así:
1. El consumidor clasifica el error: **transitorio** (red, 5xx, tiempo agotado) → `Nak` con la espera de `BackOff`;
   **permanente** (esquema inválido, versión desconocida, datos imposibles) → publica una copia en
   `lic.dlq.<stream>.<consumidor>` con cabeceras `Lic-Origen-Stream`, `Lic-Origen-Seq`, `Lic-Error`, `Lic-Intentos` y hace
   `Term`.
2. Si un mensaje llega al último intento (`NumDelivered == MaxDeliver`) sin éxito, el consumidor lo copia a la DLQ antes de
   rendirse. Como red de seguridad, un proceso de `ops` escucha los avisos
   `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.*.*` y `…MSG_TERMINATED.*.*` y copia por secuencia lo que no esté ya en la DLQ.
3. Reinyección manual con `proyector dlq reintentar --desde <seq>` (después de arreglar la causa). Nunca automática.
4. Alerta en el panel operativo si `LIC_DLQ` recibe mensajes (> 0 en 1 h) — un mensaje en la DLQ es un fallo que alguien mira.

### Idempotencia
- Cada evento tiene un `id` determinista (UUIDv5 de `tipo|fuente|id_origen|hash`, ver `api/eventos.md`) que se envía como
  **`Nats-Msg-Id`**: el broker descarta el duplicado dentro de la ventana de 2 h.
- Fuera de la ventana, el consumidor aplica solo si la `version_entidad` es mayor que la ya aplicada (ADR 0003).

### Reproducción para reconstruir proyecciones
- Ponerse al día tras una reconstrucción desde S3: consumidor nuevo con `DeliverPolicy: by_start_sequence` en la secuencia
  anotada al empezar la reconstrucción (ADR 0003), `ReplayPolicy: instant`.
- Reproducir un periodo: `DeliverPolicy: by_start_time`. Solo dentro de `MaxAge`; más atrás, desde S3.

### Permisos (usuario NATS por servicio)
| Usuario | Publica | Se suscribe / consume |
|---|---|---|
| `ingestor` | `lic.v1.>`, `lichist.v1.>` | — |
| `proyector` | `lic.dlq.>`, API de sus consumidores | `LICITACIONES`, `LIC_HISTORICO` (sus consumidores) |
| `api` | `lic.dlq.>`, API del consumidor `alertas` | `alertas` |
| `cerebro` | API del consumidor `cerebro-embudo`, `lic.dlq.LICITACIONES.cerebro-embudo` | solo `cerebro-embudo` |
| `ops` | `lic.dlq.>` | avisos `$JS.EVENT.ADVISORY.>`, `LIC_DLQ`, `ops` |
| `admin` (fuera de los servicios, en el gestor de contraseñas) | crea y cambia streams y consumidores | — |

Los streams y consumidores se declaran en código (`internal/events`, al arrancar, idempotente) con la cuenta `admin` solo
en el despliegue; los servicios no pueden borrar ni purgar streams.

## Consecuencias
- Un servicio nuevo pequeño (`nats`) y un volumen. Hay que vigilar disco: tope total ≈ 21 GiB (8 + 12 + 1).
- El patrón DLQ es código nuestro en `internal/events` (una vez, con pruebas de integración contra un NATS efímero).
- El Cerebro añade una dependencia Python (`nats-py`) en su consumidor (ADR 0007).
- Métricas obligatorias desde la fase 1 (panel operativo, §11): `num_pending`, `num_ack_pending`, `num_redelivered` por
  consumidor, edad del mensaje más antiguo sin confirmar, mensajes en `LIC_DLQ`, bytes por stream.
  Alertas: retraso de `proy-busqueda` > 15 min o > 5 000 mensajes; cualquier mensaje en la DLQ; stream > 80 % de `MaxBytes`.
- Sin alta disponibilidad: si `nats` cae, la ingesta se detiene (el outbox acumula en Postgres) y las lecturas siguen
  funcionando (OpenSearch/Redis). Aceptable para el SLO de frescura (< 2 h).

## Cómo se revisará
- Fin de la fase 1: medir RAM real de `nats`, eventos/día y tamaño medio; ajustar `MaxBytes`, `MaxAckPending` y lotes.
- Reabrir si: RAM de `nats` > 512 MB sostenida; necesidad de más de un servidor (HA real: clúster de 3 nodos JetStream);
  o > 1 mensaje/semana en la DLQ por la misma causa (problema de diseño, no de operación).
