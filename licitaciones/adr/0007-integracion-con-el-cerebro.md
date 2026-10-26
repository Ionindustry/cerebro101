# ADR 0007 — Integración con el Cerebro

- **Estado**: Aceptado como diseño; la matriz de permisos está **POR VALIDAR** con Licitaciones y Dirección
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor y quien mantiene el Cerebro
- **Relacionados**: 0002 (consumidor `cerebro-embudo`), 0003 (idempotencia), `api/openapi.yaml`, `api/eventos.md`,
  §8 del proyecto

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
| Resumen diario | Tarea programada que **consulta** la API a las 7:00 | Construirlo a partir de eventos: frágil si se pierde un consumo; la consulta es idempotente |
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
- **Resumen de las 7:00**: lo genera la tarea del **Director de Licitaciones** consultando la API
  (`GET /tenders?publicada_desde=<ayer 07:00>&encaje_min=…&orden=encaje&limit=50`); destinatarios y hora,
  POR DECIDIR por 101.cat (§12.6 del proyecto). Si el motor no responde, el resumen lo dice en vez de salir vacío.

### 4. Pantalla «Licitaciones» del panel
- Pasarela nueva `panel/app/licitaciones-api/[...ruta]/route.js`, copia de la existente con `LICITACIONES_API`
  (`http://licitaciones-api:8080/api/v1`) y **lista blanca** de rutas (`tenders`, `awards`, `organizations`,
  `competitors`, `expiring-contracts`, `alerts`, `simulations`) y de métodos (GET, POST, PATCH, DELETE). Reenvía el token de
  la sesión; en desarrollo, las cabeceras de prueba.
- Páginas en `panel/app/licitaciones/` (buscador con facetas, ficha, alertas, simulación, panel operativo). El navegador
  nunca habla con la API del motor directamente.
- `Content-Type` y código de estado se reenvían tal cual (problem+json incluido).

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

## Cómo se revisará
- Fase 3: pruebas de la API con tokens reales del realm de desarrollo (aud, iss, caducado, grupo sin permiso → 403).
- Fase 4: la matriz validada por Licitaciones y Dirección; medir el retraso de `cerebro-embudo` y cuántos expedientes entran
  al día al embudo (si son > 50/día, revisar el umbral de encaje antes de que Viabilidad se sature).
