# ADR 0007 — Integración con el Cerebro

- **Estado**: Aceptado como diseño; la matriz de permisos está **POR VALIDAR** con Licitaciones y Dirección
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor y quien mantiene el Cerebro
- **Relacionados**: 0002 (consumidor `cerebro-embudo`), 0003 (idempotencia), 0005 (caché del dashboard),
  `api/openapi.yaml`, `api/eventos.md`, §8 del proyecto («Interfaz y dashboard»)
- **Revisado**: 26/10/2026, §4 con la sección «Licitaciones» y el dashboard decididos por Dirección

## Contexto
Lo que ya existe y se reutiliza (comprobado en el repositorio el 26/10/2026):
- **Keycloak**, realm `cerebro` (`config/keycloak/realm-cerebro.json`): roles de realm `direccion`, `responsable`,
  `usuario`; un **grupo por departamento** (`licitaciones`, `comercial`, `telecom`, `areas`…); cliente público
  `cerebro-panel` con mapeadores `groups` (sin ruta completa) y de audiencia `cerebro-panel`. El emisor es fijo
  (`KC_HOSTNAME` = `KEYCLOAK_URL_PUBLICA`).
- **API del Cerebro** (`api/cerebro/api/auth.py`): valida RS256 con JWKS interno y `aud = cerebro-panel`; modo desarrollo
  con cabeceras `X-Usuario`, `X-Roles`, `X-Departamentos`.
- **Herramientas** (`api/cerebro/herramientas/base.py`): registro `Herramienta(nombre, descripcion, operaciones, externas,
  ayuda, ejemplos…)`; todo pasa por `usar()`, que comprueba ficha, sensibilidad (`config/herramientas.yaml`),
  aprobación de operaciones externas y deja traza en Langfuse.
- **Panel** (Next.js): pasarela `panel/app/cerebro/[...ruta]/route.js` que reenvía al API con el token de la sesión.
- **Tareas programadas**: Celery (`worker`, `beat`) con colas `peticiones` y `lote` en el Redis del Cerebro; el calendario
  sale del campo `horario` de las fichas.
- **Red** Docker `cerebro`; solo Caddy publica 80/443 en producción; la API del Cerebro no se publica (`docs/DESPLIEGUE.md`).
- Tabla `licitaciones` del Cerebro (`db/esquema.sql`): `expediente UNIQUE`, viabilidad, decisión, estado (sin uso hoy).

## Opciones (para cada punto de integración se eligió la de menos piezas nuevas)
| Punto | Elegida | Descartada y por qué |
|---|---|---|
| Identidad | Keycloak del Cerebro, mismo realm | Usuarios propios del motor: dos inicios de sesión y dos políticas de permisos |
| Agentes → motor | Herramienta Python que llama a la API HTTP del motor | Acceso directo a OpenSearch/grafo desde Python: salta la autorización y duplica consultas |
| Motor → Cerebro (novedades) | Consumidor NATS **ligero** que solo escribe en Postgres | Encolar una tarea de Celery (o una ejecución de agente) por evento: es exactamente el atasco de octubre (1,1 M tareas) |
| Resumen diario | Tarea programada que **consulta** la API a las 16:00 | Construirlo a partir de eventos: frágil si se pierde un consumo; la consulta es idempotente |
| Panel | Segunda pasarela en el panel hacia la API del motor | Llamar al motor desde el navegador: obligaría a publicar la API |

## Decisión

### 1. Keycloak
- **Cliente `licitaciones-api`** (confidencial, sin flujos: `standardFlowEnabled`, `directAccessGrantsEnabled`,
  `serviceAccountsEnabled` a `false`): solo representa la audiencia de la API del motor.
- Al cliente `cerebro-panel` se le añade un **mapeador de audiencia** `licitaciones-api`: el token de sesión del panel vale
  para las dos APIs (una sola sesión).
- **Cliente `cerebro-agentes`** (confidencial, `serviceAccountsEnabled: true`, *client credentials*), con mapeadores de
  audiencia `licitaciones-api` y `groups`; su cuenta de servicio está en el grupo `licitaciones` y tiene el rol de realm
  nuevo `servicio`. Su secreto (`LICITACIONES_CLIENTE_SECRETO`) va solo a `api` y `worker` del Cerebro (lista cerrada del
  `docker-compose.yml`, y `api/tests/test_entorno.py` lo comprobará).
- **Validación en la API Go** (`internal/auth`, con `github.com/coreos/go-oidc/v3`): JWKS desde la URL interna
  `http://keycloak:8080/realms/cerebro/protocol/openid-connect/certs` (caché; recarga ante un `kid` desconocido, como mucho
  cada 5 min); solo `RS256`; `iss` = `${KEYCLOAK_URL_PUBLICA}/realms/cerebro`; `aud` contiene `licitaciones-api`;
  `exp`/`nbf` con 30 s de tolerancia; `azp` ∈ {`cerebro-panel`, `cerebro-agentes`}. Usuario = `preferred_username`;
  roles = `realm_access.roles`; departamentos = `groups`. Errores 401 sin detalles del token.
- Modo desarrollo (`LIC_MODO=desarrollo`): mismas cabeceras `X-Usuario/X-Roles/X-Departamentos` que el Cerebro; en
  cualquier otro valor se ignoran. Por defecto, producción.

**Matriz de autorización (propuesta, POR VALIDAR)** — se comprueba en cada *handler*, no solo en el *router*:
| Recurso | Quién |
|---|---|
| `GET /tenders`, `/tenders/{id}`, `/tenders/{id}/history`, `/expiring-contracts`, `/awards` | grupos `licitaciones`, `direccion`, `comercial`, `telecom`, `areas`; cuenta `servicio` |
| `GET /organizations/{id}` (compradores) | igual que la fila anterior |
| `GET /organizations/{id}` (proveedores), `/competitors` | `licitaciones`, `direccion`; `servicio`. El NIF y el nombre de **personas físicas** solo se devuelven a estos y cada acceso queda registrado |
| `POST /simulations`, `GET /simulations/{id}` | `licitaciones`, `direccion`; `servicio`. Una simulación solo la ve su departamento (contiene el coste propio) |
| `/alerts` ámbito `personal` | el propio usuario |
| `/alerts` ámbito `departamento` | crear/cambiar: rol `responsable` de ese departamento o `direccion`; ver: miembros del departamento |
| `GET /dashboard/opportunities` | como `/tenders` (no contiene datos personales) |
| `GET /dashboard/market` | como `/awards`; el apartado `top_competidores` solo para `licitaciones`, `direccion` y `servicio` (como `/competitors`, acceso registrado); a los demás les llega `null` con `alcance = sin_competidores` |
| `GET /ops/status` alcance `resumen` (estado global, motivos, fuentes, estado de cada componente) | como `/tenders`: todo el que ve el dashboard tiene que ver cuándo las cifras no son fiables |
| `GET /ops/status` alcance `detalle` (colas, DLQ, proyecciones, indicadores de cada almacén) | rol `direccion`, grupo `tecnologia`, rol `responsable` del grupo `licitaciones`; cuenta `servicio` |
| API del Cerebro `GET /licitaciones/embudo/resumen` (§4) | rol `direccion` y grupo `licitaciones` (`comercial`: POR VALIDAR) |

Registro de accesos: cada petición deja usuario, `azp`, ruta, parámetros (sin datos personales), resultado y duración
(registro estructurado + traza OTel). Las peticiones de agentes llevan `X-Agente` y `X-Traza` (id de Langfuse) **solo
para auditoría**: nunca amplían permisos.

### 2. Herramienta `licitaciones` de los agentes
- Fichero nuevo `api/cerebro/herramientas/licitaciones.py` (fase 4), mismo patrón que las demás (`registrar(Herramienta(…))`).
- Cliente `httpx.AsyncClient` reutilizado, `LICITACIONES_API_URL` (por defecto `http://licitaciones-api:8080`),
  tiempo de conexión 2 s y total 10 s (`simular`: 30 s), 1 reintento solo en errores de conexión de operaciones de lectura.
- Token: *client credentials* de `cerebro-agentes`, cacheado en memoria hasta 30 s antes de `exp`.
- Operaciones (§8) → endpoint: `buscar` → `GET /tenders`; `ficha` → `GET /tenders/{id}`; `historial` → `…/history`;
  `adjudicaciones` → `GET /awards`; `organismo` → `GET /organizations/{id}`; `competidores` → `GET /competitors`;
  `contratos_que_vencen` → `GET /expiring-contracts`; `novedades_desde` → `GET /tenders?actualizada_desde=…&orden=actualizacion`;
  `simular` → `POST /simulations` (devuelve la curva; **no decide**).
- Ninguna operación es `externa` (no tienen impacto fuera): no requieren aprobación. Presentarse y firmar siguen siendo
  decisiones humanas (sin cambios en `politicas_aprobacion.yaml`).
- Resultados recortados para el contexto del modelo (`limit` 10 por defecto, campos resumidos) y errores HTTP traducidos a
  mensajes para el agente (problem+json → `detail`).
- `config/herramientas.yaml`: `licitaciones: {local: true, sensibilidad_max: alta}`. **Desviación de §8** («sensibilidad
  baja»): los datos del motor son públicos, pero `simular` recibe el **coste propio** desde el agente Precio
  (`sensibilidad: alta` en su ficha); con `baja`, Precio no podría usarla. Como el motor es local (mismo servidor, red
  interna), no sale ningún dato. A validar por quien mantiene el Cerebro.
- `plataformas_contratacion` conserva `descargar_documento` y `preparar_paquete`; `novedades` se retira cuando el
  Rastreador use `licitaciones`.

### 3. Consumidor de eventos en el Cerebro y resumen diario
- Servicio nuevo `licitaciones-eventos` en el compose del Cerebro: **misma imagen que la API**, comando
  `python -m cerebro.licitaciones.consumidor`, cliente `nats-py`, consumidor *durable* `cerebro-embudo` (ADR 0002:
  `MaxAckPending` 100, lotes de 20). Variables: solo `DATABASE_URL` (rol `cerebro_app`), `NATS_URL`, `NATS_USUARIO`,
  `NATS_CLAVE`, `LICITACIONES_ENCAJE_MIN`. Sin claves de modelos ni de ERP.
- Qué hace por evento (y nada más): `licitacion.nueva` con `encaje ≥ LICITACIONES_ENCAJE_MIN` → *upsert* en la tabla
  `licitaciones` del Cerebro (estado `detectada`); `.adjudicada`/`.anulada` → actualiza el estado si el expediente está en
  el embudo. **No ejecuta agentes ni encola tareas.** Idempotente por versión (ADR 0003). Migración de la fase 4: columnas
  `motor_id uuid UNIQUE`, `motor_version int`, `encaje numeric`.
- El **Rastreador** (6:00, ya programado por su ficha) lee el embudo y pide a **Viabilidad** el informe ir/no ir de las
  `detectada` — el trabajo con modelos sigue en la cola `lote`, acotado por el número de expedientes del día.
- **Resumen de las 16:00**: lo genera la tarea del **Director de Licitaciones** consultando la API
  (`GET /tenders?publicada_desde=<ayer 16:00>&encaje_min=…&orden=encaje&limit=50`); lo recibe Dirección (decidido por
  101.cat el 26/10/2026, §12.6 del proyecto). Si el motor no responde, el resumen lo dice en vez de salir vacío.

### 4. Sección «Licitaciones» del panel (decidida por Dirección el 26/10/2026, §8 del proyecto)

#### Pasarela
- Pasarela nueva `panel/app/licitaciones-api/[...ruta]/route.js`, copia de la existente con `LICITACIONES_API`
  (`http://licitaciones-api:8080/api/v1`) y **lista blanca por prefijo y método**: `tenders`, `awards`, `organizations`,
  `competitors`, `expiring-contracts`, **`dashboard`**, **`ops`** → solo GET; `alerts` → GET, POST, PATCH, DELETE;
  `simulations` → GET, POST. Cualquier otra combinación → 404 en la pasarela, sin llegar al motor. Reenvía el token de la
  sesión; en desarrollo, las cabeceras de prueba.
- `Content-Type` y código de estado se reenvían tal cual (problem+json incluido). Plazo de la pasarela hacia el motor: 5 s
  (30 s para `simulations`); si se agota, 504 problem+json.
- El navegador nunca habla con la API del motor directamente. El bloque del embudo va por la pasarela que ya existe
  (`/cerebro/...`) a la API del Cerebro.

#### Pestañas y rutas del panel (`panel/app/licitaciones/`)
| Pestaña | Ruta del panel | Datos de | Fase |
|---|---|---|---|
| **Dashboard** | `/licitaciones` (`?periodo=hoy\|7d\|30d\|90d`, por defecto `7d`) | ver «Bloques» | 3 (Oportunidades, Estado del motor) · 4 (Competencia y mercado, Embudo propio) |
| **Buscador** | `/licitaciones/buscar?<parámetros de GET /tenders>` | `GET /tenders` (facetas en la primera página) | 3 |
| **Ficha** | `/licitaciones/expedientes/[id]` | `GET /tenders/{id}`, `/tenders/{id}/history` | 3 básica (resumen, lotes, importes con significado, plazos, enlaces a las fuentes originales, encaje explicado) · 4 completa (historial de versiones, documentos, adjudicaciones, botón «Estudiar») · 5b «Simular» |
| **Competencia** | `/licitaciones/competencia` (ranking), `/licitaciones/competencia/adjudicaciones?<parámetros de GET /awards>`, `/licitaciones/competencia/vencen?<parámetros de GET /expiring-contracts>`, `/licitaciones/organizaciones/[id]` | `/competitors`, `/awards`, `/expiring-contracts`, `/organizations/{id}` | 4 (listados y ranking) · 5 (fichas de competidor y organismo completas, actas, alertas de competencia) |
| **Alertas** | `/licitaciones/alertas` | `/alerts` | 4 |
| **Estado del motor** | `/licitaciones/estado` | `GET /ops/status` (alcance según rol) | 3 (mismo endpoint que el bloque del dashboard: no añade backend) |
| (embudo, desde el bloque 3) | `/licitaciones/embudo?estado=…` | API del Cerebro `GET /licitaciones?estado=…` (fase 4, a proponer con la migración) | 4 |

Los enlaces del dashboard llegan como `EnlaceListado` (`ruta` del motor + `parametros` exactos). El panel traduce solo la
ruta (`/tenders` → `/licitaciones/buscar`, `/awards` → `/licitaciones/competencia/adjudicaciones`, `/expiring-contracts`
→ `/licitaciones/competencia/vencen`, `/competitors` → `/licitaciones/competencia`) y copia los parámetros a la query:
la URL de cada listado se puede compartir y reproduce la cifra.

#### Bloques del dashboard y de dónde sale cada uno
| Bloque | Endpoint | Fuente de datos | Caché | Fase |
|---|---|---|---|---|
| 1. Oportunidades | motor `GET /dashboard/opportunities?periodo=` | OpenSearch `tenders` (agregaciones sobre campos precalculados en la proyección) | Redis `lic:dash:op:*`, 5 min (ADR 0005) | 3 |
| 2. Competencia y mercado | motor `GET /dashboard/market?periodo=` | OpenSearch `awards` (sin grafo) | Redis `lic:dash:mer:*`, 15 min, con el alcance de permisos en la clave | 4 |
| 3. Embudo propio | **Cerebro** `GET /licitaciones/embudo/resumen?dias=` | tabla `licitaciones` del Cerebro | ninguna (consulta pequeña en Postgres) | 4 |
| 4. Estado del motor | motor `GET /ops/status` | instantánea en memoria de `cmd/api` (cada 15 s): `ingestion_runs`, NATS `:8222`, salud de OpenSearch, grafo, MinIO, Redis y Postgres | sin Redis (tiene que poder decir que Redis está caído) | 3 |

**Un endpoint por bloque, no uno compuesto.** Motivos:
- *Permisos*: cada bloque tiene una regla distinta (Oportunidades como `/tenders`; Mercado con competidores restringidos;
  `/ops/status` con dos alcances; el embudo en otra API). Uno compuesto obligaría a mezclar reglas en una respuesta y a
  multiplicar las variantes de caché.
- *Caché*: cada bloque se invalida con una cosa distinta (generación de `tenders`, de `awards`, nada) y tiene un TTL
  distinto (5 min, 15 min, 15 s en memoria). Compuesto, el TTL sería el del más corto y se recalcularía todo.
- *Latencia y fallos*: el panel pide los cuatro en paralelo; el p95 de la carga es el del más lento, no la suma, y un
  bloque lento o caído no tumba los demás (cada uno muestra su error). Coste: 4 peticiones por carga a través de la
  pasarela (~1–2 ms cada una en la red interna), asumible.

**Reglas comunes**: periodo `hoy`/`7d`/`30d`/`90d` con límites a medianoche (Europe/Madrid); universo = nuestras áreas
CPV (`AreaCpv`, los 20 CPV de §12.1 en 5 áreas) y España; unidad de cuenta el **lote** (como `/tenders`, para que cifra =
`total` del listado); importes siempre `Importe` con significado e IVA (presupuesto base sin IVA en Oportunidades,
adjudicado sin IVA en Mercado) y sin mezclar: lo que no tiene ese dato se cuenta aparte. Cada bloque lleva `frescura`
(`calculado_en`, generación del índice, `estado_motor`); si `/ops/status` dice `caido`, el panel pinta el bloque en rojo
y **no muestra cifras** (§8). Ninguna cifra la calcula la IA.

**Embudo propio (Cerebro, fase 4; la tabla, el cálculo, las rutas y la pantalla están hechos, falta el consumidor de eventos)**. Implementado en `api/cerebro/licitaciones/embudo.py`; ver «Embudo propio» en `docs/PROYECTO_LICITACIONES.md` §Estado para las diferencias con lo propuesto abajo (cambio de estado por `POST`, identidad por `motor_id`, motivos de pérdida POR VALIDAR). Endpoint propuesto en `api/cerebro/api/main.py`, mismo estilo que
`/aprobaciones/resumen`:
```python
@app.get("/licitaciones/embudo/resumen")
async def resumen_embudo(dias: int = 30, usuario: Usuario = Depends(usuario_actual)):
    """Dashboard de Licitaciones, bloque «Embudo propio»: por estado, en el periodo, tasa de éxito y motivos de pérdida."""
    # 403 si no es rol direccion ni grupo licitaciones
    return await embudo.resumen(dias)   # api/cerebro/licitaciones/embudo.py: consulta + calcular_resumen(filas, dias, zona) pura y probada sola
```
`dias` = 1 (hoy, desde las 00:00 en la zona de la empresa), 7, 30 o 90 (el panel traduce el periodo), acotado a 1–365 como
en Aprobaciones. Respuesta: `{dias, por_estado: {detectada, en_estudio, presentada, ganada, perdida, descartada}` (foto
actual), `en_periodo: {detectadas, presentadas, ganadas, perdidas, descartadas}`, `tasa_exito: {valor, ganadas, decididas}`
(ganadas / (ganadas + perdidas) resueltas en el periodo; `valor` null con menos de 5 decididas), `motivos_perdida: [{motivo,
total}]` (top 5), `horas_hasta_decision_p50` (indicador del §11)`}`. Requiere ampliar la migración de la fase 4 (§3): además
de `motor_id`, `motor_version` y `encaje`, `estado` con `CHECK` sobre esos seis valores, `motivo_perdida text` (lista
cerrada a acordar con Licitaciones), `actualizado`, `decidida_en`, `presentada_en` y `resuelta_en` (`timestamptz`).

#### Primera versión (final de la fase 3) y resto
- **Fase 3**, solo lectura: pasarela con la lista blanca completa (los prefijos aún sin *handler* devuelven 404 del motor);
  Dashboard con **Oportunidades** y **Estado del motor**; Buscador; Ficha básica; pestaña Estado del motor. Los bloques 2 y
  3 no se muestran (ni con datos de ejemplo).
- **Fase 4**: bloques Competencia y mercado y Embudo propio; pestañas Competencia (listados y ranking) y Alertas; Ficha
  completa con «Estudiar» (crea o actualiza la fila del embudo vía la API del Cerebro).
- **Fase 5**: fichas completas de competidor y organismo, actas, alertas de competencia. **5b**: «Simular».

### 5. Red Docker y qué se publica
- Red nueva **`licitaciones`** con `internal: true` (sin salida a internet): `nats`, `licitaciones-minio`,
  `licitaciones-redis`, OpenSearch, grafo, proyectores, `licitaciones-api`.
- Solo dos servicios se unen además a la red `cerebro`: `licitaciones-api` (para el panel y la herramienta) y `nats`
  (para `licitaciones-eventos`, con su usuario de permisos mínimos). Keycloak lo alcanza la API por la red `cerebro`.
  Postgres: la base `licitaciones` vive en el servidor `postgres` existente; el ingestor, la API y los proyectores que la
  usan se unen a `cerebro` solo si no hay otra vía — **POR DECIDIR en la fase 1**: alternativa, un alias de `postgres` en
  la red `licitaciones`.
- **Salida a internet**: solo el `ingestor` (y el descargador de documentos), por una red de salida propia, con la lista
  blanca de fuentes y los controles anti-SSRF en código (`NORMAS.md`). Si se añade un *proxy* de salida lo decide el
  modelo de amenazas (`licitaciones/docs/SEGURIDAD.md`).
- **Publicado fuera: nada.** Ningún puerto en el host en producción; en desarrollo, como mucho `127.0.0.1:8090` para la
  API del motor. Caddy no gana rutas nuevas: el panel es la única entrada.
- Todos los contenedores del motor: usuario no root, `read_only: true` cuando sea posible, `cap_drop: [ALL]`, límites de
  memoria y CPU (presupuesto en `licitaciones/README.md`).

## Consecuencias
- Cambios en el Cerebro, todos en la **fase 4** y en PR separados: realm (clientes, mapeador, rol `servicio`),
  `docker-compose.yml` (servicio `licitaciones-eventos`, variables nuevas en `x-api` y su prueba), herramienta,
  `config/herramientas.yaml`, fichas que la usen (`scripts/generar_fichas.py`), migración de la tabla `licitaciones` y
  pasarela del panel.
- Dependencia nueva en el Cerebro: `nats-py`.
- Si el motor cae, el Cerebro sigue funcionando: la herramienta devuelve un error claro y el resumen avisa.
- **Índices de OpenSearch** (lo implementa quien lleve la búsqueda en la fase 3): para que los agregados del dashboard
  sean agregaciones simples sin *scripts* y cada cifra coincida con su listado, la proyección precalcula en `tenders` y
  `awards`: `areas` (keyword, de `config/areas_cpv.yaml`, con la regla de jerarquía de CPV en un solo sitio); `nuts` con
  **todos sus ancestros y el país** (`ES512` → `ES`, `ES5`, `ES51`, `ES512`), y `ES` también en los documentos de
  PLACSP y Cataluña sin NUTS (así `nuts=ES` no pierde el ~13 % sin lugar); `provincia` (NUTS 3 o vacío); importes
  normalizados en céntimos (`long`) por significado e IVA (`presupuesto_base_sin_iva`, `adjudicado_sin_iva`); en
  `awards`, `resultado`, `baja`, `fecha_adjudicacion` y `fecha_fin_contrato`. Parámetro nuevo `area` en `/tenders`,
  `/awards`, `/competitors`, `/expiring-contracts` y en el filtro de alertas; `resultado` en `/awards`.
- La caché del dashboard añade dos tipos de clave a ADR 0005.

## Cómo se revisará
- Fase 3: pruebas de la API con tokens reales del realm de desarrollo (aud, iss, caducado, grupo sin permiso → 403).
- Fase 3, dashboard: (1) prueba de contrato «cifra = total del enlace» para cada `Cifra` con `cuenta_igual_a_total`;
  (2) k6 sobre el corpus con la caché **fría y caliente**: p95 de cada endpoint del dashboard (objetivo de la carga
  completa p95 < 300 ms, medido como el máximo de los cuatro en paralelo a través de la pasarela). La decisión de calcular
  los agregados al vuelo es **provisional**: si en frío `/dashboard/opportunities` o `/dashboard/market` pasan de 250 ms
  de p95, se añade un índice de resumen diario (`tenders_resumen_diario`, un documento por día × área × provincia ×
  tramo de encaje, recalculado por el proyector para los días tocados) o el precalentado de las 4 claves de periodo al
  cambiar la franja; no antes. (3) `/ops/status` p95 < 20 ms con todos los almacenes parados (prueba de caos con el
  compose).
- Fase 4: la matriz validada por Licitaciones y Dirección; medir el retraso de `cerebro-embudo` y cuántos expedientes entran
  al día al embudo (si son > 50/día, revisar el umbral de encaje antes de que Viabilidad se sature).
