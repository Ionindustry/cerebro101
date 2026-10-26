# Proyecto: motor de búsqueda de licitaciones integrado en el Cerebro

> Convierte el documento «Plataforma de detección y análisis de concursos públicos» (octubre de 2026) en un proyecto
> ejecutable, con **su arquitectura objetivo** (§12: Go, base de datos de grafos, S3, OpenSearch y mensajería) e integrado con
> el Cerebro. Objetivo de negocio: **cada mañana, las licitaciones nuevas que encajan con 101.cat, ordenadas por interés**, con su
> ficha, plazos y análisis; un buscador para todo lo publicado en España y la UE; el **histórico de adjudicaciones** para
> analizar a la competencia, y un **simulador** que estima la probabilidad de ganar y el margen según el precio ofertado.

## 1. Decisiones de arquitectura

El documento propone dos pilas que se contradicen (§5 habla de HTTPX, lxml, Prefect/Airflow y Celery; §12 exige Go). Se sigue
**§12**, que es la arquitectura objetivo, y se eliminan las piezas redundantes:

| Capa | Elección | Motivo |
|---|---|---|
| Conectores e ingesta | **Go** (`cmd/ingestor`): clientes HTTP reutilizables, *workers* acotados, XML en *streaming* (`encoding/xml.Decoder`), puntos de control y *backoff* | §12.2 |
| Planificación | Planificador dentro del ingestor (cron + cerrojo de líder) | Sustituye a Prefect/Airflow y Celery (§5): un sistema menos |
| Mensajería | **NATS JetStream** | Más ligero que Kafka para un servidor; entrega al menos una vez, *dead-letter* y reproducción del log (§12.6) |
| Originales | **S3** sobre **MinIO** en el propio servidor (bucket `raw` y `processed`, versionado, cifrado, Object Lock para los originales) | §12.5, sin depender de una nube externa; cambiar a AWS S3 es solo configuración |
| Relaciones | **Base de datos de grafos**: Neo4j o Memgraph, elegida con el banco de pruebas de la fase 0 | §12.3 y §12.7 |
| Búsqueda | **OpenSearch** (texto completo, CPV, facetas, *ranking* y búsqueda semántica) | §12.2: «no sustituirlo por recorridos de grafo» |
| Caché | **Redis** propio | §12.2 |
| Datos operativos | **PostgreSQL** (base `licitaciones`, en el servidor de Postgres existente): usuarios de alertas, reglas, entregas, ingestas, *outbox* | Las entidades `alerts`, `users` e `ingestion_runs` del §4 son transaccionales: un grafo no es buen sitio para ellas |
| API | **Go** (`cmd/api`, `chi`, REST/JSON con OpenAPI; gRPC interno) | §6 y §12.2 |
| Autenticación | **Keycloak del Cerebro** (realm `cerebro`, cliente `licitaciones-api`); roles y departamentos de siempre | Mismo inicio de sesión y permisos que el panel |
| Interfaz | Pantalla **«Licitaciones» del panel** del Cerebro (Next.js) | §5 pide Next.js; el panel ya lo es |
| Observabilidad | OpenTelemetry, métricas RED, `pprof`; trazas a Langfuse/OTel del Cerebro | §12.2 |
| Infraestructura | **OpenTofu** para el servidor y servicios; `docker compose` en desarrollo; CI/CD en GitHub Actions | §12.8 |

**Dónde vive el código**: carpeta `licitaciones/` dentro del repositorio `cerebro101` (un PR por cambio y la misma CI, con un
trabajo de Go nuevo). Estructura de §12.8: `cmd/api`, `cmd/ingestor`, `internal/connectors`, `internal/domain`, `internal/graph`,
`internal/search`, `internal/storage`, más `internal/events`, `internal/scoring` y `api/openapi.yaml`.

### Flujo
```
 PLACSP 643 ─┐                          ┌─► S3/MinIO raw/{fuente}/{año}/{mes}/{id}/{sha256}.xml   (evidencia inmutable)
 PLACSP 1044 ┼─► ingestor Go ─► NATS ───┤
 TED v3 ─────┤   (parsers         JetStream  ├─► proyector de grafo ──► Neo4j / Memgraph   (relaciones, historial)
 Cataluña ───┘    versionados)          └─► proyector de búsqueda ─► OpenSearch            (búsqueda, facetas, ficha precalculada)
                                                      │
              API Go ◄── Redis (caché) ◄──────────────┘          Postgres «licitaciones»: alertas, entregas, ingestas, outbox
                │
                ├─► panel del Cerebro (pantalla «Licitaciones»)
                ├─► herramienta «licitaciones» de los agentes (Rastreador, Viabilidad, Inteligencia Competitiva, Precio…)
                └─► eventos «licitacion.nueva / modificada / adjudicada» ─► alertas y resumen diario de las 16:00
```
El S3 conserva la evidencia; el grafo y OpenSearch son **proyecciones reconstruibles** desde S3 y el log de NATS (§12.6).

## 2. Lo que hay hoy en el Cerebro

- Herramienta `plataformas_contratacion`: lee un feed ATOM/CODICE y filtra por CPV e importe, pero **no tiene fuentes
  configuradas** (`config/integraciones.yaml`: `feeds: []`), solo lee la primera página y no guarda nada. Hoy el Rastreador no detecta licitaciones.
- Tabla `licitaciones` del Cerebro (viabilidad, decisión ir/no ir) sin uso: pasa a ser el **embudo comercial** y apunta al expediente del motor.
- Agentes de Licitaciones listos para usar los datos: Rastreador (6:00), Viabilidad, Analista de Pliegos, Inteligencia Competitiva (4:00), Precio…
- Cuadernos de investigación con citas (PR #22): base para analizar pliegos citando el fragmento exacto.
- Servicios aprovechables: Postgres, Keycloak, Ollama con `bge-m3` (embeddings para la búsqueda semántica), panel Next.js.

## 3. Fuentes (comprobadas desde el servidor el 26/10/2026)

| Fuente | Acceso | Comprobado | Uso |
|---|---|---|---|
| PLACSP — perfiles del contratante (sindicación 643) | ATOM/CODICE paginado (`rel="next"`) y ZIP mensuales | 200 OK; ~68 entradas y ~2 MB por página; ZIP de septiembre de 2026: 92 MB | Ingesta nacional e histórico |
| PLACSP — plataformas agregadas, sin menores (sindicación 1044) | ATOM/CODICE paginado | 200 OK; ~300 entradas por página; **incluye la plataforma de Cataluña** | Cobertura autonómica |
| TED — Search API v3 | `POST https://api.ted.europa.eu/v3/notices/search` (sin clave para buscar); XML eForms por anuncio | 200 OK con consulta por país, CPV y fecha | Anuncios UE y adjudicaciones |
| Transparència Catalunya (`ybgg-dgi6`) | API Socrata (JSON) | 200 OK (`codi_expedient`, `nom_organ`, `fase_publicacio`…) | Contraste y enriquecimiento |
| PLACSP — contratos menores | Feed propio | **Por verificar en la fase 0** | El volumen real de un instalador |

Cadencia: las fuentes publican cada hora (entradas de las 02:00 y las 03:00 en la muestra). Ingesta incremental **cada hora**,
revisión diaria de expedientes activos y reconciliación semanal (§7 del documento).

## 4. Modelo de grafo y de búsqueda

**Grafo** (§12.3): nodos `Procedure`, `Notice`, `NoticeVersion`, `Lot`, `Organization`, `Award`, `Contract`, `CPV`, `Document`,
`Source`; relaciones `PUBLISHED_BY`, `HAS_NOTICE`, `HAS_VERSION`, `HAS_LOT`, `AWARDED_TO`, `CLASSIFIED_AS`, `REFERENCES`,
`DERIVED_FROM`, `SUPERSEDES`. Se añaden `LOCATED_IN` (NUTS) y `COMPETED_IN` (licitadores de un lote, cuando el acta los publica)
para el análisis de competencia. IDs estables por fuente + UUID interno; **nunca se fusionan entidades por nombre** (organismos por
DIR3/NIF; empresas por NIF).

**Índices de OpenSearch** (con alias para reindexar sin cortes):
- `tenders`: un documento por expediente y lote, desnormalizado (organismo, CPV, NUTS, importes con su significado, plazos,
  estado observado y normalizado, puntuación de encaje). Analizadores de castellano y catalán, sinónimos de CPV y campo
  `knn_vector` con el embedding `bge-m3` del objeto del contrato (búsqueda **híbrida** BM25 + semántica).
- `awards`: adjudicaciones para análisis de mercado (series temporales, importes, bajas).
- La **ficha** completa se precalcula en la proyección: el detalle sale de OpenSearch o Redis sin tocar el grafo ni S3 (§12.4).

## 5. Adjudicaciones y análisis de la competencia

El motor guarda **todo el ciclo de cada expediente**, no solo el anuncio de licitación: adjudicación, formalización,
modificaciones, desistimientos y concursos desiertos. Es la base del análisis de competencia y de los precios.

### Qué se guarda de cada adjudicación (por lote)
| Dato | Origen | Para qué |
|---|---|---|
| Adjudicatario: nombre y **NIF** (clave del nodo `Organization`) | CODICE (PLACSP) y eForms (TED) | Identificar al competidor sin depender de cómo escriba su nombre cada organismo |
| Importe adjudicado sin y con IVA, y presupuesto base y valor estimado del lote | CODICE / eForms | Calcular la **baja** (adjudicado frente a presupuesto base) |
| Número de ofertas recibidas; oferta más baja y más alta (cuando se publican) | CODICE / eForms | Intensidad de competencia y dispersión de precios |
| Fecha de adjudicación y de formalización; duración y **fecha de fin** del contrato; prórrogas | Anuncios de adjudicación y formalización | Saber **cuándo vuelve a salir** un contrato |
| Procedimiento, criterios (precio frente a calidad) y si hubo baja anormal | Anuncio y pliego | Comparar resultados entre concursos parecidos |
| Licitadores no adjudicatarios, puntuaciones y motivos de exclusión | Actas de la mesa (PDF) | Ranking completo de competidores (fase 5; solo cuando el acta se publica) |
| Modificaciones del contrato y su importe | Anuncios de modificación | Coste real final frente a lo adjudicado |

Los campos concretos de CODICE y eForms se fijan con el corpus real de la fase 0. Cada dato guarda su fuente, el original en S3
y el nivel de confianza.

### En el grafo
`(:Organization {buyer})-[:PUBLISHED_BY]-(:Procedure)-[:HAS_LOT]->(:Lot)<-[:AWARDED_TO {importe, baja, fecha}]-(:Organization {supplier})`,
más `COMPETED_IN` (licitadores de un lote, desde las actas) y `CLASSIFIED_AS` (CPV). Así salen en 1–2 saltos: competidores de un
CPV en una zona, a quién adjudica cada organismo, contra quién se compite y quién gana a quién.

### Análisis que ofrece (API, panel y agentes)
1. **Ficha de competidor**: contratos ganados, importes, cuota por CPV, zona y organismo, baja media, tendencia por trimestre.
2. **Ficha de organismo**: a quién adjudica, con qué baja media, cuántas ofertas recibe y cuánto se repite el mismo adjudicatario.
3. **Cuotas de mercado** por CPV y zona, y su evolución.
4. **Precio de referencia** para el agente Precio: baja media y percentiles en concursos parecidos (mismo CPV, organismo e
   importe) y riesgo de **baja anormal**.
5. **Contratos que vencen**: contratos de nuestros CPV que terminan en los próximos 3–12 meses → el concurso volverá a salir.
   Es la mejor fuente de oportunidades anticipadas, y encaja con el modelo de negocio («anticipar tendencias y demanda»).
6. **Alertas de competencia**: «el competidor X ha ganado en un organismo que nos interesa», «nuevo competidor en CCTV en Girona».
7. **Tasa de éxito propia** (101.cat como licitador) y motivos de pérdida, cruzando con el embudo del Cerebro.

### Histórico
Para que estos análisis sirvan hace falta más historia que para buscar licitaciones abiertas. Propuesta: **5 años** de
adjudicaciones desde los ZIP mensuales de PLACSP y los anuncios de TED, cargados en paralelo una vez en la fase 1.

### Datos personales
Algunos adjudicatarios son **autónomos** (personas físicas): su nombre y NIF son datos personales. Se guardan porque son
públicos y necesarios para el análisis (interés legítimo, con evaluación documentada). Se usan solo para análisis de mercado,
no se exportan en bloque y respetan las condiciones de reutilización de cada fuente.

## 6. Simulador de presentación de ofertas

Con el histórico de adjudicaciones, antes de presentarse a un concurso se puede **simular el resultado**: quién se presentará,
con qué bajas, cómo puntuará la mesa y con qué probabilidad gana 101.cat según el precio que ofrezca.

### Cómo funciona
1. **Reglas del concurso**: el Analista de Pliegos extrae de los pliegos, citando el fragmento, la fórmula de puntuación
   económica, el peso de precio y calidad, los criterios automáticos y el criterio de **baja anormal** (el del pliego o, si no
   lo fija, el reglamentario). Una persona las valida antes de simular.
2. **Competidores probables**: desde el grafo, quién se presenta y gana en ese organismo, CPV, zona y tramo de importe, con su
   frecuencia. Si el concurso tiene histórico propio (un contrato que vence), los que se presentaron la última vez.
3. **Comportamiento de cada competidor**: distribución de sus bajas en concursos parecidos; si hay pocos datos, la del mercado
   (CPV y zona). El número de ofertas esperado sale del histórico del organismo.
4. **Puntuación técnica**: estimación del Evaluador para 101.cat (con rango de confianza) y, para los competidores, sus
   puntuaciones históricas cuando las actas las publican.
5. **Simulación Monte Carlo** (miles de escenarios): en cada uno se sortean los competidores que se presentan y sus bajas; se
   aplica la fórmula económica del pliego, el umbral de baja anormal (que depende de las demás ofertas) y la puntuación total.
6. **Resultado**: para cada precio posible de 101.cat, la **probabilidad de ganar**, el riesgo de entrar en baja anormal y,
   con el coste real del agente Costes (ERP y cotizador), el **margen esperado**. Se recomienda el precio con mejor margen
   esperado dentro del riesgo que fije Dirección.

### Reglas
- **Todo el cálculo es código determinista** (principio del Cerebro: los importes no los calcula la IA). La IA solo extrae
  las reglas del pliego con cita, y una persona las confirma.
- **Calibración con el pasado (*backtesting*)**: se simulan concursos ya adjudicados como si no se supiera el resultado y se
  compara con lo que pasó. El simulador muestra su precisión y no se usa para decidir mientras no la alcance.
- Siempre se muestra la **incertidumbre** (rangos, no un único número) y cuántos datos hay detrás de cada competidor.
- La decisión del precio y la presentación siguen siendo humanas (aprobación «doble» del agente Precio, como hoy).

### Dónde se usa
- **Agentes**: Precio (precio recomendado y riesgo), Evaluador (puntuación de la mesa), Viabilidad (probabilidad de ganar en
  el informe ir/no ir) y Director de Licitaciones.
- **Panel**: en la ficha del concurso, botón «Simular»: curva de probabilidad de ganar y margen esperado según el precio,
  competidores probables y escenarios. Se pueden cambiar supuestos (puntuación técnica, quién se presenta) y volver a simular.
- **Aprendizaje**: cuando se adjudica un concurso al que 101.cat se presentó, se compara la simulación con el resultado real.

### Técnica
Servicio `internal/simulation` en Go (rápido y paralelo: 10 000 escenarios por concurso en menos de un segundo es
el objetivo), con los datos del grafo y de OpenSearch (`awards`). Las fórmulas de puntuación más comunes se implementan como
módulos con pruebas, y si un pliego trae una fórmula nueva, se añade como módulo nuevo, nunca se improvisa.

## 7. Mejoras sobre el documento original

**Rendimiento**
1. **Ficha precalculada (CQRS)**: el detalle de un expediente es una lectura por id en Redis/OpenSearch → p95 < 75 ms holgado.
   El grafo solo se consulta para relaciones (competidores, historial).
2. **Ingesta incremental real**: se recorre `rel="next"` solo hasta la última entrada vista (punto de control por fuente), con
   `If-Modified-Since`/ETag donde la fuente lo admita. El histórico se carga una vez desde los ZIP mensuales, en paralelo por mes.
3. **Parsers en *streaming*** con memoria constante (un ZIP de 92 MB no se carga entero) y versionados por formato.
4. **Proyecciones idempotentes y en lote**: escrituras al grafo con `UNWIND`/lotes de 500–1 000 y `bulk` de OpenSearch;
   el consumidor guarda el último hash aplicado y descarta repeticiones.
5. **Búsqueda paginada con `search_after`** y facetas precalculadas; nunca `from/size` profundos.
6. **Pliegos bajo demanda**: solo se descargan los documentos de expedientes que encajan o que alguien abre (el documento los
   descarga todos). Ahorra disco, ancho de banda y antivirus.
7. **Aislamiento de recursos**: el motor no comparte cola ni GPU con Jarvis; la IA solo se usa para lo que encaja. Presupuesto de
   memoria fijado por servicio (OpenSearch y el grafo compiten por la RAM del servidor con Ollama).
8. **Mensajería que no se desborda**: límites `MaxAckPending`, caducidad de mensajes, *dead-letter* y métricas de retraso. Es la
   lección del atasco de octubre de 2026 en el Cerebro (1,1 millones de tareas encoladas sin que nadie lo viera).

**Funcionalidad**
9. **Puntuación de encaje para 101.cat**, calculada al proyectar: CPV de las 10 áreas, zona (Cataluña primero, NUTS ES51),
   importe frente a la solvencia, días hasta el cierre y procedimiento. El resumen diario sale ordenado por ella.
10. **Búsqueda semántica**: «cámaras de seguridad» encuentra «sistema de videovigilancia» aunque el CPV no coincida.
11. **Pliegos con citas**: cuaderno de investigación por expediente; el Analista de Pliegos extrae requisitos, solvencia y criterios
    **citando el fragmento**, como exige §3 («enlazar a la fuente y fragmento original, con nivel de confianza»).
12. **Inteligencia de competencia en el grafo**: quién gana en cada organismo y CPV, bajas medias, redes comprador-proveedor.
    Alimenta al agente Precio (umbral de baja anormal) y a Inteligencia Competitiva.
13. **Plazos al calendario** del Cerebro: fin de presentación, aclaraciones y plazo de recurso.
14. **Contratos menores**, si se confirma la fuente.
15. **Jarvis responde al momento** «¿qué licitaciones hay hoy de videovigilancia en Girona?» desde la API.

## 8. Integración con el Cerebro

- **Herramienta `licitaciones`** (cliente de la API Go; local, sensibilidad baja): `buscar`, `ficha`, `historial`, `adjudicaciones`,
  `organismo`, `competidores`, `contratos_que_vencen`, `novedades_desde` y `simular` (devuelve la curva probabilidad-precio-margen;
  no decide). `plataformas_contratacion` conserva `descargar_documento` y `preparar_paquete`.
- **Eventos → Cerebro**: un consumidor en el Cerebro recibe `licitacion.nueva` con encaje alto y la registra en el embudo; el
  **Rastreador** (6:00) pide a **Viabilidad** el informe ir/no ir; el **Director de Licitaciones** prepara el resumen que Dirección recibe a las 16:00 en el panel.
- **Panel**: pantalla «Licitaciones» (buscador con facetas, ficha, alertas guardadas, panel operativo), a través de la pasarela del panel.
- **Seguridad**: tokens de Keycloak validados en la API Go; la API no se publica fuera (como la del Cerebro); registro de accesos.
- Las aprobaciones no cambian: presentarse y firmar siguen siendo decisiones humanas.

### Interfaz y dashboard (decidido por Dirección el 26/10/2026)
Una sección **«Licitaciones»** dentro del panel del Cerebro (mismo inicio de sesión de Keycloak, mismos permisos por rol y
departamento, mismo aspecto). El navegador nunca habla con la API del motor: pasa por la pasarela del panel (ADR 0007).

| Pestaña | Contenido | Datos de |
|---|---|---|
| **Dashboard** | Cuatro bloques (abajo), con periodo seleccionable (hoy, 7, 30, 90 días) y clic en cada cifra para ver el listado | API del motor + API del Cerebro |
| **Buscador** | Texto libre (híbrido BM25 + semántico), facetas por área CPV, provincia/NUTS, organismo, importe, estado, plazo y fuente; orden por encaje, fecha o importe; paginación por cursor | `GET /tenders` |
| **Ficha** | Expediente y lotes, importes con su significado, plazos, documentos, historial de versiones, enlaces a las fuentes originales, puntuación de encaje explicada; botones «Estudiar» (pasa al embudo del Cerebro) y «Simular» (fase 5b) | `/tenders/{id}`, `/history` |
| **Competencia** | Ficha de competidor y de organismo, cuotas de mercado, bajas medias, contratos que vencen | `/competitors`, `/organizations`, `/expiring-contracts`, `/awards` |
| **Alertas** | Búsquedas guardadas con aviso (en el panel y en el resumen de las 16:00) | `/alerts` |
| **Estado del motor** | Indicadores operativos del §11 | `GET /ops/status` |

**Bloques del dashboard**
1. **Oportunidades**: licitaciones nuevas del periodo con encaje alto (ordenadas por encaje), importe total, plazos que cierran
   en 7 días, reparto por área CPV (TI, videovigilancia, tráfico, control de accesos, redes) y por provincia.
2. **Competencia y mercado**: adjudicaciones recientes en nuestros CPV, competidores que más ganan y su cuota, baja media por
   área, contratos que vencen en 3–12 meses.
3. **Embudo propio**: licitaciones en estudio, presentadas, ganadas y perdidas; tasa de éxito y motivos de pérdida. Sale de la
   tabla `licitaciones` del Cerebro (embudo comercial), no del motor.
4. **Estado del motor**: frescura por fuente (objetivo < 2 h), última ingesta correcta, errores de parser, retraso de las colas
   de NATS, salud de OpenSearch, grafo, MinIO y Redis. Si algo falla, el dashboard lo dice en rojo en vez de mostrar cifras viejas.

**Rendimiento**: los agregados del dashboard se precalculan en la proyección de OpenSearch y se cachean en Redis (TTL corto);
objetivo de carga del dashboard p95 < 300 ms. Ninguna cifra del dashboard la calcula la IA.

**Entregas**: primera versión **adelantada al final de la fase 3** (Dashboard con Oportunidades y Estado del motor, Buscador y
Ficha básica, solo lectura); el resto (Competencia, Embudo, Alertas, Ficha completa) en la fase 4 y «Simular» en la 5b.

## 9. Objetivos de rendimiento (SLO del documento, §12.1)

Búsqueda p95 < 100 ms y p99 < 250 ms; vecindad del grafo (1–2 saltos) p95 < 50 ms; ficha p95 < 75 ms; disponibilidad de lectura
99,9 % mensual. Son hipótesis: se validan con k6 sobre el corpus de la fase 0 antes de comprometerlas.

## 10. Fases (un PR por entrega)

| Fase | Duración orientativa | Entregables | Se acepta cuando… |
|---|---|---|---|
| **0. Descubrimiento y PoC** | 2–3 semanas | Corpus de muestras reales (643, 1044, TED, Cataluña) como datos de prueba; feed de menores verificado; **banco de pruebas Neo4j vs Memgraph** (§12.7) con corpus sintético de 1 M expedientes y 5 M anuncios/versiones: p50/p95/p99, CPU, RAM, disco, ingestión por segundo, HA y recuperación, caché fría y caliente; **ADR** de grafo, mensajería, caché y consistencia; decisiones de la sección 12 | ADR aprobados y muestras en `licitaciones/testdata/` |
| **1. Datos** | 3 semanas | Esqueleto Go (`cmd/*`, `internal/*`), MinIO y NATS en el compose; conector PLACSP 643/1044 incremental con **anuncios y adjudicaciones** (adjudicatario por NIF, importes, bajas, nº de ofertas, formalización y fin del contrato); parser CODICE versionado con pruebas de contrato; originales con SHA-256; proyector de grafo | Repetir la ingesta no duplica; cada registro tiene original, hash y URL; carga histórica de **5 años** de licitaciones y adjudicaciones |
| **2. Más fuentes** | 2 semanas | Conector TED v3 (eForms); reconciliación PLACSP–TED conservadora (identificadores, evidencia y confianza); contraste con Cataluña | Un expediente presente en PLACSP y TED aparece una vez, con la evidencia del enlace |
| **3. Búsqueda y API** | 3–4 semanas | Proyector de OpenSearch (híbrido BM25 + semántico); puntuación de encaje; API Go con OpenAPI, Keycloak, paginación por cursor, límites y caché Redis; endpoints del dashboard y `/ops/status`; **primera versión de la sección «Licitaciones» del panel** (Dashboard con Oportunidades y Estado del motor, Buscador, Ficha básica; solo lectura) | Búsqueda por texto, CPV, zona, organismo, fechas y estado; contrato OpenAPI publicado; Dirección usa el dashboard con datos reales |
| **4. Cerebro y panel** | 3 semanas | Herramienta `licitaciones`; consumidor de eventos; nuevo Rastreador y resumen de las 16:00; resto de la sección «Licitaciones» (Competencia, Embudo propio, Alertas, Ficha completa con «Estudiar») | Criterios del MVP del documento (§9) cumplidos y el resumen diario llega solo |
| **5. Pliegos y competencia** | 3 semanas | Descarga bajo demanda con antivirus; cuaderno por expediente con matriz de cumplimiento citada; fichas de competidor y de organismo, cuotas de mercado, **contratos que vencen** y alertas de competencia (§5); actas de mesa (licitadores y puntuaciones) cuando se publican; plazos al calendario | El Analista de Pliegos cita página y fragmento; la ficha de un competidor cuadra con una muestra revisada a mano |
| **5b. Simulador de ofertas** | 3 semanas | Módulo `internal/simulation` (§6): fórmulas de puntuación con pruebas, baja anormal, Monte Carlo, curva probabilidad-precio-margen; *backtesting* con concursos ya adjudicados; botón «Simular» en el panel; uso por Precio, Evaluador y Viabilidad | El *backtesting* alcanza la precisión acordada con Licitaciones antes de usarse para decidir |
| **6. Producción** | 2 semanas | OpenTofu; OpenTelemetry y paneles; pruebas k6/Vegeta reproducibles; copias y ensayo de restauración (RPO/RTO); reindexado completo desde S3 | SLO medidos y cumplidos; restauración ensayada |

Total orientativo: **20–24 semanas** con una persona dedicada, más la revisión de Licitaciones. Cada fase acaba en algo usable.

## 11. Indicadores del panel operativo

Los del §7 del documento: **frescura** (publicación oficial → ingesta; objetivo < 2 h), **cobertura** (muestra auditada),
**completitud** por fuente, **duplicados** sin reconciliar, **fiabilidad** (ingestas correctas, errores de parser) y
**trazabilidad** (original, hash y URL). Además: retraso de los consumidores de NATS, licitaciones con encaje alto por día y tiempo
hasta la decisión ir/no ir.

## 12. Decisiones que necesito de 101.cat (fase 0)

Decididas por Dirección el 26/10/2026: todas. La 8 se decide con los resultados del banco de pruebas (ADR 0006).

1. **CPV de interés** (decidido; sustituye a la propuesta inicial): 72000000-5, 72200000-7, 72230000-6, 72262000-9,
   72267000-4 (servicios TI, desarrollo y mantenimiento de software); 32323500-8, 32235000-9, 32234000-2, 35125300-2,
   35120000-1 (videovigilancia, cámaras y sistemas de vigilancia y seguridad); 34970000-7, 34923000-3, 34971000-4,
   34972000-1, 63712710-3, 45316210-0 (control, vigilancia y medición del tráfico, y su instalación); 42961000-0,
   42961100-1 (mando y control, control de accesos); 32420000-3 (equipos de red); 32441100-7 (vigilancia telemétrica).
   Propuesta por validar: puntuar también la jerarquía (un CPV hijo de uno de la lista encaja; p. ej. 72000000 cubriría toda la división 72).
2. **Zona prioritaria** (decidido): **España**. Se ingesta todo y se puntúa por zona. **Andorra queda fuera** (decidido el
   26/10/2026): su fuente (`contractacio.govern.ad`, registro exportable sin NIF ni CPV) no permite la reutilización sin
   autorización escrita del Govern. Se puede replantear si se obtiene (ver `licitaciones/testdata/andorra/PROCEDENCIA.md`).
3. **Histórico** (decidido): **5 años** de licitaciones y adjudicaciones (carga inicial en la fase 1).
4. **Importes** (decidido): **hasta 1 000 000 €**, sin mínimo. Se ingesta todo; el límite cuenta en la puntuación de encaje y
   en el resumen diario. Se aplica al **presupuesto base de licitación sin IVA de cada lote** (confirmado por Dirección).
5. **Contratos menores** (decidido): **sí se incluyen**. Su fuente se verifica en la fase 0.
6. **Resumen diario** (decidido): lo recibe **Dirección (Albert)** a las **16:00**, con lo publicado desde las 16:00 del día anterior.
7. **Servidor** (decidido): **este mismo servidor** (62 GB compartidos con el Cerebro y Ollama). Cada servicio del motor lleva
   límite de memoria y CPU (NORMAS) y el presupuesto se fija con el banco de pruebas.
8. **Licencias**: Neo4j Community (sin clúster) o Enterprise; Memgraph Community (BSL). Afecta a la alta disponibilidad.
   Se decide con los resultados del banco (ADR 0006).

## 13. Riesgos

| Riesgo | Medida |
|---|---|
| **Memoria del servidor**: OpenSearch (montón JVM), el grafo (Memgraph trabaja en memoria) y Ollama en la misma máquina | Presupuesto de RAM por servicio desde la fase 0; si no cabe, servidor aparte para el motor |
| Muchos servicios nuevos que operar (Go, grafo, OpenSearch, NATS, MinIO) | OpenTofu, OpenTelemetry, alertas de salud en el panel operativo y procedimientos de restauración desde la fase 6 |
| Cambios de formato (CODICE, eForms) | Parsers versionados, pruebas de contrato con el corpus y aviso de campos desconocidos |
| Cobertura incompleta | Auditoría por muestra y contraste entre PLACSP, TED y Cataluña |
| Falsos duplicados | Reconciliación solo por identificadores oficiales; revisión humana de los dudosos |
| Pliegos mal interpretados | Siempre con cita; decisión y firma humanas |
| Confiar de más en el simulador (pocos datos de un competidor, fórmula mal leída) | Reglas del pliego validadas por una persona; *backtesting* obligatorio; rangos de incertidumbre y nº de datos siempre visibles |
| Actas de mesa incompletas o en PDF escaneado | Se usan solo cuando están; OCR con revisión; el simulador funciona también solo con adjudicaciones |
| Malware en documentos | Antivirus antes de guardar; solo se extrae texto |
| Licencias de los motores | Decidir en el ADR de la fase 0 |

## 14. Referencias
PLACSP (datos abiertos): https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/licitaciones_plataforma_contratacion.aspx ·
TED Search API: https://docs.ted.europa.eu/api/latest/search.html · Swagger TED: https://api.ted.europa.eu/swagger ·
Transparència Catalunya: https://analisi.transparenciacatalunya.cat/ · Cataluña, integración: https://contractaciopublica.cat/es/manuals/integrador ·
Documento de partida: «Plataforma de detección y análisis de concursos públicos» (octubre de 2026).
