# Subvenciones y financiación (ARES Funding Intelligence) — Fase 1

Radar de ayudas, subvenciones y financiación pública integrado en ARES. Código en `api/cerebro/subvenciones/`, catálogo de fuentes en `config/subvenciones.yaml`, panel en **Subvenciones**.

## Estado honesto (léelo primero)

| Pieza | Estado |
|---|---|
| Núcleo (modelo, normalización, deduplicación, historial, sincronización idempotente, estados, búsqueda, radar, seguimiento personal) | **Hecho y probado** (unitarias, tubería en memoria y Postgres real). |
| Conector **BDNS (ES-001)** | **Verificado parcialmente el 19/11/2026 con respuestas reales** desde el servidor de 101.cat: `GET /convocatorias/busqueda` (paginación estándar con `content`, `last`, `totalElements`) y `GET /convocatorias?numConv=` responden JSON y los campos usados existen (`numeroConvocatoria`, `organo`, `presupuestoTotal`, `sectores`, `regiones`, `instrumentos`, `urlBasesReguladoras`, `abierto`…). Ajustes hechos con esos datos: `abierto=false` no se traduce en «cerrada» (sin fechas queda UNKNOWN); la región «ES431 - Badajoz» (NUTS) se guarda como provincia; los documentos de la BDNS no traen dirección de descarga y no se importan. **Pendiente**: una sincronización manual completa desde el panel y la decisión de Dirección de activarla; no hay Swagger público en las rutas probadas. |
| **UE (EU-001)** | Conector `sedia` escrito con una respuesta real (19/11/2026): solo anuncios de tipo 8; tipos 1 y 2 sin verificar, no se importan. Falta sincronización manual y activación por Dirección. |
| **Cataluña (ES-003, CIDO)** | Conector `cido` escrito con datos reales (19/11/2026). **Limitación**: el dataset no trae plazo ni importe; el estado sale solo del campo `estat`; confianza baja. Licencia «ver términos de uso» (atribución Consorci AOC / CIDO). Falta sincronización manual y activación. |
| **BOE (ES-002)** | Conector `boe` escrito con datos reales (19/11/2026), **solo-enlace**: los «Extractos» de convocatoria (sección 5B) citan `BDNS(Identif.):N` en su XML; el conector añade a la convocatoria de la BDNS la procedencia «BOE» y el documento del extracto, **sin crear oportunidades propias ni tocar su estado ni sus datos**. Si la convocatoria aún no está en la BDNS se omite y se enlaza cuando llegue (se relee una ventana de 7 días). Pendiente: correcciones, anulaciones y ampliaciones de plazo. Falta sincronización manual y activación. |
| Resto (autonómicas, diputaciones, Andorra…) | **Catalogadas como pendientes de verificar. Sin conector.** Nada se da por conectado. |
| Cruce con empresas (matching), alertas, análisis de documentos con IA | **No hechos** (Fases 2–4). El radar muestra «relevantes para tu empresa» vacío con su aviso. |

**Una fuente nunca se activa sola.** Solo pasa a «habilitada» si tiene conector y una sincronización **manual** previa terminó bien (lo comprueba el servidor, no solo el botón).

## Cómo verificar BDNS (en tu servidor, ventana Ubuntu)

```
cd /home/user/cerebro101   # (en tu equipo: /home/pc/cerebro101)
./scripts/subvenciones_verificar.sh
```

Solo lectura: GET públicos, sin claves. Prueba la documentación Swagger, la búsqueda y un detalle, guarda muestras en `subvenciones_muestras/` y dice qué campos esperados aparecen. Si hay ✘: no actives la fuente; ajusta `endpoint_*`, `param_*` o `campos` en los ajustes de ES-001 (`PATCH /subvenciones/fuentes/ES-001` con `ajustes`) y repite. Después: panel › Subvenciones › Conectores › **Sincronizar ahora**, revisa que entren datos razonables, y solo entonces **Activar**.

## Arquitectura

- **Conector** (`conectores/`): trae páginas de SU fuente y normaliza cada registro al modelo unificado. No guarda, no deduplica, no decide estados. Un conector nuevo se añade en `conectores/__init__.py` sin tocar el núcleo. Reintentos con backoff, pausa de cortesía, tope de páginas por ejecución, `User-Agent` identificado, sin credenciales.
- **Normalización** (`normalizar.py`, pura): fechas, importes, instrumento (según lo que declara la fuente, nunca por intuición del título), estado del ciclo de vida por fechas, huellas.
- **Segunda fuente**: nunca pisa el estado, las huellas ni los datos ya conocidos de la fuente que creó la oportunidad (solo rellena huecos y deja la procedencia). Corregido en esta fase: antes una segunda fuente podía sobrescribir el estado.
- **Deduplicación** (`deduplicar.py`): mismo registro de la misma fuente → referencias citadas de otras fuentes → identificador canónico propio (`BDNS:…`, `EU:…`) → huella exacta (`FP:…`). **No hay fusión por parecido**: dos convocatorias parecidas se quedan separadas antes que fusionar mal. Una segunda fuente solo rellena huecos, nunca pisa a la prioritaria.
- **Sincronización** (`sincronizar.py`): idempotente (huella de la fuente y huella normalizada), historial de cambios por campo, punto de reanudación por página, aislamiento entre fuentes (un fallo no para a las demás), ejecución anotada (leídos/nuevos/modificados/sin cambios/inválidos/error). Si ≥ la mitad de los registros son inválidos la ejecución queda «parcial».
- **Estados**: NEW/UPDATED no son del ciclo de vida: «nueva» y «modificada» se **calculan al consultar** (ventana `dias_novedad`). El ciclo de vida (OPENING_SOON, OPEN, CLOSING_SOON, CLOSED, CANCELLED, UNKNOWN) se recalcula con el calendario de hoy. Sin fechas ni declaración: UNKNOWN (no se inventa).
- **Base de datos** (`db/esquema.sql`, idempotente): `funding_sources`, `funding_sync_runs`, `funding_opportunities`, `funding_source_records`, `funding_opportunity_changes`, `funding_documents`, `funding_saved_opportunities`. Búsqueda de texto en español (`tsvector`).
- **Celery**: `sincronizar_subvenciones` cada hora (cada fuente respeta su frecuencia; BDNS 4 h) y `sincronizar_subvencion` (manual), cola `lote`.
- **API** (`/subvenciones/…`): ver y buscar cualquier persona con sesión (datos públicos); seguir/guardar, cada persona lo suyo; **conectores solo Dirección**.
- **Panel**: Radar (nuevas, abiertas, próximas a abrir/cerrar, modificadas), Buscador con filtros, Ficha (procedencia, documentos, historial), Mis oportunidades, Conectores.

## Agentes asociados (herramienta `subvenciones`, solo lectura)

| Agente | Para qué |
|---|---|
| `ayudas` (Ayudas y Subvenciones) | Detectar ayudas aplicables a clientes, vigilar plazos y novedades. |
| `estratega` | Financiación pública en objetivos y escenarios. |
| `tesorero` | Préstamos, avales y financiación pública en la previsión de caja. |
| `analista-noticias` | Ayudas y normativa como inteligencia de mercado. |
| `prevision-demanda` | Ayudas que mueven demanda (p. ej. eficiencia, digitalización). |
| `esp-renovables` | Ayudas del sector energético (IDAE, comunidades). |

Los agentes comerciales y de precios **no** la reciben (mínimo privilegio). `config/herramientas.yaml`: sensibilidad máx. «alta», local, no sale ningún dato.

## Principios que cumple

- El modelo **interpreta y redacta**; la lectura de fuentes, la validación, los permisos, los estados, las fechas y la persistencia son **código determinista**.
- Lo que devuelven las fuentes es **texto de terceros**: se trata como datos, no como instrucciones; en el panel solo se enlazan `http(s)`.
- La herramienta **no tiene operaciones de escritura**: presentar solicitudes, guardar para alguien o activar una fuente son decisiones de personas.
- Los filtros se validan y se parametrizan (nunca se concatenan al SQL).
- No se tocan prompts de agentes activos, aprobaciones, CRM, ERP ni fórmulas de precio.

## Desviaciones respecto al documento de diseño

- `is_new` y `has_changes` se **calculan** al consultar (no son columnas): evitan quedar desfasadas.
- Tablas `funding_alerts`, `funding_matches`, `funding_company_profiles` y preferencias: **aplazadas** a las fases de matching y alertas.
- Un único identificador canónico `BDNS:` compartido con las fuentes que citen el número BDNS (BOE, autonómicas) en vez de una tabla de equivalencias aparte.

## Riesgos y pendientes

1. BDNS: falta la sincronización manual completa y revisar datos reales antes de activarla. Primera carga: cientos de convocatorias en la última semana, con una petición de detalle cada una (pausa de cortesía): tarda; se reparte en ejecuciones de hasta 40 páginas con punto de reanudación. El aviso legal de la BDNS restringe la reutilización y permite limitar accesos abusivos: no se sube el ritmo de peticiones.
2. Cuotas o bloqueos del servicio oficial: hay tope de páginas, pausas y reintentos; si falla, la fuente queda con su error anotado y no se activa.
3. La UE (Funding & Tenders) exige estudiar su API (paginación, tipos, estados) antes de escribir el conector; no se ha hecho.
4. No hay todavía cruce con empresas ni alertas: «relevantes para tu empresa» está vacío a propósito.
5. Fases siguientes: UE → BOE/autonómicas/Andorra → perfiles de empresa y matching explicable → alertas → análisis de documentos con IA (siempre citando texto oficial y separando lo oficial de lo inferido).

## Análisis de una convocatoria (paso 1)

En la ficha de cada convocatoria, el bloque **Análisis** ordena lo que la fuente oficial ya dijo en tres apartados: **de qué trata**, **a quién va dirigida** y **bases para presentarse** (requisitos, exclusiones,
gastos subvencionables, importes, calendario, estado, cómo solicitar, bases reguladoras y documentos). No usa IA: no inventa nada. Lo que la fuente no dice aparece como «No consta en la fuente» y en la lista de
`lagunas`; la **cobertura** (completa / parcial / escasa) avisa de cuánto se ha podido extraer (las fuentes de listado, como Cataluña, traen poco). Los agentes lo consultan con `subvenciones › analisis`
(solo lectura) y el panel con `GET /subvenciones/oportunidades/{id}/analisis`. No dice si 101.cat cumple los requisitos ni es una valoración jurídica.

Siguientes pasos (aún no hechos): leer el PDF de las bases con descarga segura y citas literales (en borrador hasta que una persona lo confirme) y cruzar los requisitos con el perfil de la empresa.
