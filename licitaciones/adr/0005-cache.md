# ADR 0005 — Caché: Redis propio del motor

- **Estado**: Aceptado (TTL y tamaños de partida; se ajustan con la tasa de aciertos medida en la fase 3)
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor
- **Relacionados**: 0003 (versiones), SLO §9 del proyecto

## Contexto
- SLO: búsqueda p95 < 100 ms, ficha p95 < 75 ms. La ficha se precalcula en la proyección (CQRS, §7.1) y se lee por id.
- Las agregaciones de competencia (cuotas, bajas medias por CPV y zona) son caras en OpenSearch y cambian poco.
- `NORMAS.md`: nada de S3 ni del grafo en la ruta de búsqueda; límites de tasa en la API.
- El Cerebro ya tiene dos Redis: `redis` (broker de Celery, **sin contraseña**, sin límite de memoria) y `redis-panel`
  (sesiones). Mezclar la caché del motor con el broker de Celery repetiría el problema de octubre: una pieza sin límites
  compartida por dos sistemas.

## Opciones
| Criterio | A. Redis propio del motor | B. Reutilizar `redis` del Cerebro | C. Sin caché (solo OpenSearch) | D. Caché en memoria del proceso de la API |
|---|---|---|---|---|
| Aislamiento (memoria, contraseña, desalojo) | Total: `maxmemory` + `allkeys-lru` + ACL | Ninguno: desalojar podría borrar tareas de Celery | n/a | Por proceso |
| Coste de RAM | ~1 GB | 0 | 0 | Por réplica de la API |
| Ficha p95 (estimación, a medir) | ~1–3 ms en acierto | igual | GET por id en OpenSearch: ~5–20 ms (a medir) | < 1 ms, pero sin invalidación compartida |
| Límite de tasa compartido entre réplicas | Sí | Sí | No | No |

Criterio decisivo: la caché tiene que poder **desalojar sin riesgo** y **no compartir fallos** con el Cerebro.

## Decisión
**A. `licitaciones-redis`** (Redis 7, imagen fijada), solo en la red interna del motor.
- `--maxmemory 768mb --maxmemory-policy allkeys-lru --save '' --appendonly no` (es una caché: se puede perder entera);
  contenedor limitado a **1 GB**.
- ACL por servicio: `lic-api` (lectura/escritura en `lic:*`), `lic-proyector` (escritura en `lic:ficha:*` y `lic:gen:*`);
  sin `default` habilitado, sin comandos `FLUSH*`, `KEYS`, `CONFIG`.
- Si Redis no responde (> 20 ms), la API **sigue sin caché** (va a OpenSearch) y lo cuenta en una métrica: la caché nunca
  es necesaria para funcionar.

### Qué se cachea
| Clave | Contenido | Escribe | TTL | Invalidación |
|---|---|---|---|---|
| `lic:ficha:{g}:{tender_id}` | Ficha precalculada (JSON comprimido) con su `version_entidad` | Proyector (al aplicar) y API (en fallo de caché) | 24 h | Por versión (abajo) |
| `lic:busq:{g}:{sha256(consulta normalizada + ámbito de permisos)}` | Primera página de resultados y facetas | API | 60 s | Por generación `{g}` y TTL |
| `lic:agg:{g_awards}:{sha256(parámetros)}` | Competidores, cuotas, bajas, contratos que vencen | API | 1 h | Por generación de `awards` y TTL |
| `lic:org:{g_awards}:{org_id}:{sha256(parámetros)}` | Estadísticas de organismo/competidor | API | 1 h | Igual |
| `lic:rl:{usuario}:{ventana}` | Contadores de límite de tasa | API | duración de la ventana | — |
| `lic:gen:tenders`, `lic:gen:awards` | Número de generación del índice | Proyector | sin TTL | Se incrementa al cambiar el alias (reindexado) |

**No** se cachean: páginas con cursor más allá de la primera (cambian con cada escritura), simulaciones (se guardan en
Postgres), datos de alertas, ni nada que contenga el coste propio de 101.cat.

La clave de búsqueda incluye el **ámbito de permisos** (p. ej. si el usuario puede ver NIF de personas físicas): dos
usuarios con permisos distintos nunca comparten una entrada.

### Invalidación por versión (fichas)
Escritura condicional con un *script* Lua de una línea: `SET` solo si la clave no existe o su `version_entidad` es menor que
la nueva. La usan tanto el proyector (escritura directa tras aplicar en OpenSearch) como la API (al rellenar tras un fallo).
Así, una lectura antigua de la API nunca pisa una versión más nueva escrita por el proyector. Caso límite aceptado: si la
clave se desaloja justo entre la escritura del proyector y la de la API con datos viejos, queda una ficha antigua como
máximo **24 h** (el TTL). La ficha lleva `version_entidad`, así que la reconciliación semanal (ADR 0003) puede contar
estos casos; si aparecen, se baja el TTL.

Reindexado completo (ADR 0003): al cambiar el alias se incrementa `lic:gen:*`; todas las claves de la generación anterior
quedan huérfanas y las desaloja el LRU/TTL. Sin `FLUSH` ni barridos.

## Consecuencias
- Un servicio más pequeño (1 GB). Memoria acotada por diseño.
- Métricas: aciertos/fallos por tipo de clave, latencia de Redis, desalojos (`evicted_keys`). Si los desalojos son
  constantes con tasa de aciertos < 50 %, la caché no sirve: se revisa tamaño o se quita el tipo de clave.
- El proyector depende de Redis solo de forma «blanda»: si Redis no está, aplica en OpenSearch y sigue.

## Cómo se revisará
Fase 3, con k6 sobre el corpus: medir ficha y búsqueda **con y sin** caché. Si OpenSearch solo ya cumple los SLO con
margen (p95 < 50 % del objetivo), se elimina la caché de búsqueda y se deja solo la de agregaciones (menos piezas).
