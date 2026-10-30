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

### Búsqueda por significado y por cercanía (hecha)
Además de la búsqueda de texto (palabras exactas), el motor busca **por sentido**: «cámaras de seguridad» encuentra «videovigilancia» aunque no compartan
palabras. Decisión: **pgvector dentro del mismo Postgres del motor** (imagen `pgvector/pgvector:pg16`, misma versión 16 que antes) en vez de una base
vectorial o de grafos aparte (OpenSearch, Neo4j): con ~65.000 expedientes (cientos de miles con el histórico) un índice HNSW en Postgres responde en
milisegundos, se puede **combinar con los filtros** (CPV, zona, estado, importe) en la misma consulta, no añade otro servicio que cuidar ni otra copia
de los datos. Si algún día hay decenas de millones de documentos o hace falta recorrer relaciones de varios saltos, se revisa (§5, grafo).
- **Vectorizador** (`cmd/vectorizador`): servicio pequeño que, con el modelo `bge-m3` de Ollama (1024 dimensiones, el mismo del Cerebro), calcula el vector de
  cada expediente a partir de su título, comprador, tipo de contrato y CPV; los más recientes primero, por lotes, y revectoriza lo que cambia. Tabla
  `expedientes_vectores` (la crea él, no una migración: si la base no tiene pgvector, el motor sigue igual y solo esta búsqueda queda desactivada).
- **API**: `GET /tenders?q=…&modo=significado|hibrido` (por defecto `texto`, como siempre; con `cercania` 0–1 en cada resultado; sin paginación) y
  `GET /tenders/{id}/parecidas` (los más cercanos, con el porqué: `mismo_comprador`, `cpv_comun`). El modo `hibrido` mezcla texto y significado
  (fusión por rangos recíprocos) y, si Ollama no responde, devuelve la búsqueda de texto con un `aviso`.
- **«Grafo» sin base de grafos**: la cercanía «por relaciones» (mismo comprador, mismo CPV) se resuelve con las relaciones que ya están en Postgres y se
  muestra junto a la cercanía de significado.
- **Panel**: selector «Cómo buscar» en el buscador y tarjeta «Licitaciones parecidas» en la ficha. **Agentes**: `licitaciones.buscar(modo=…)` y `licitaciones.parecidas`.
- **Cuidado con la versión del sistema de la imagen**: `postgres:16` (a fecha de octubre de 2026) se basa en Debian *trixie* (glibc 2.41) y `pgvector/pgvector:pg16-bookworm` en *bookworm* (glibc 2.36). Cambiar de una a otra con datos ya creados da el aviso
  «collation version mismatch» y los índices de texto pueden quedar mal ordenados: hay que ejecutar `REINDEX DATABASE licitaciones;` y `ALTER DATABASE licitaciones REFRESH COLLATION VERSION;` (con ingestor, proyector y vectorizador parados). Por eso la etiqueta está fijada a `pg16-bookworm`.
- **Primera vez**: la base cambia a la imagen con pgvector (haz antes una copia, `scripts/copia_seguridad.sh`) y el vectorizador tarda en recorrer todo
  (del orden de 1 hora por cada ~50.000 expedientes en CPU; se ve en los registros `licitaciones-vectorizador-1`). Mientras tanto, la búsqueda por
  significado va devolviendo lo que ya está vectorizado.

### Dashboard de la pantalla de búsqueda (hecho)
`/licitaciones/buscar` ya no es solo un formulario y una lista: arriba hay un **dashboard** de TODO lo que cumple los filtros (no solo de la página que se ve), con los filtros en una **barra lateral plegable** y los resultados en una **tabla**.
- **Cifras**: resultados, importe total y medio (valor estimado sin IVA), abiertas y las que vencen en 7 días. **Repartos**: por estado, por tramo de importe, por zona (provincia) y por sector (división CPV). **Calendario** de plazos de los próximos 60 días y **principales organismos** (con su importe).
- **Pulsar un estado, una zona o un sector filtra la búsqueda** (otra pulsación lo quita); la dirección de la página sigue siendo la búsqueda, así que se puede compartir.
- **Tabla ordenable**: Importe, Plazo (el más próximo primero) y Actualizada se ordenan en el motor pulsando su cabecera. En el móvil la tabla se desplaza en horizontal.
- **Motor**: `GET /tenders/estadisticas` (mismos filtros que `/tenders`; en `licitaciones/internal/storage/pg/estadisticas.go`). Una consulta por reparto sobre el mismo `WHERE`, y el estado es el efectivo (una «abierta» con el plazo pasado cuenta como «cerrada»). Con la búsqueda «por significado» las cifras cuentan por palabras (el aviso se muestra en pantalla). Si el motor es anterior a esta función, el dashboard avisa de que hay que actualizarlo y la lista sigue funcionando.

### Oferta de la licitación (primera entrega)
Del pliego a la oferta, con los agentes de Oferta técnica y económica trabajando sobre **un mismo borrador** por licitación (`cerebro/licitaciones/ofertas.py`, herramienta `ofertas`, tarjeta «Oferta» en la ficha; solo Dirección y Licitaciones).
- **Tres sobres, en secciones.** «Preparar la oferta» crea las secciones **a partir del pliego** (no de una plantilla fija): una por criterio de juicio de valor de la ficha (con sus puntos), la descripción de la solución, los criterios valorables por fórmula, la
  proposición económica y la justificación del precio, y la declaración responsable/DEUC, la solvencia y otros documentos. Cada sección lleva su **guía** (lo que pide el pliego) y los **requisitos confirmados** que debe cubrir; la ficha muestra qué requisitos técnicos aún no cita ninguna sección.
- **Los agentes solo escriben borradores** (`ofertas.guardar_seccion`; también `plan`, `leer` y `seccion`). No pueden revisar ni aprobar, ni fijar el precio, ni escribir la proposición económica, ni pisar una sección que una persona editó, revisó o aprobó. Lo que citan son ids de requisitos que **existen y están confirmados** en esa licitación
  (no se pueden inventar). Quién escribe lo pone el sistema, no el modelo. Cada versión queda en el historial.
- **Las personas** escriben y corrigen en el panel (la sección vuelve a «borrador» y hay que revisarla), la marcan como **revisada** o **aprobada**, y **fijan el precio** (con el simulador como ayuda). Con el precio se genera sola la proposición económica (importe, IVA y total).
- **Word editable** (`.docx`, sin librerías nuevas): portada, sobres y secciones; lo no aprobado sale marcado `[BORRADOR — pendiente de revisión]`, las secciones vacías `[SECCIÓN SIN REDACTAR]` y, sin precio, `[PRECIO PENDIENTE]`; en el sobre administrativo añade la relación de requisitos con su cumplimiento (matriz).
- **No se presenta nada desde aquí:** una persona revisa, firma y presenta en la plataforma. Los agentes con acceso: Redactor de Memoria, Arquitecto de Solución, Administrativo, Costes y Precio.
- **Segunda entrega (pendiente):** el botón «Redactar con agentes», que lanza a los agentes sobre las secciones vacías de forma asíncrona (con el modelo local la generación es lenta: unos pocos tokens por segundo, así que una sección larga tarda minutos) y enseña el progreso.

### Vigilante de la ingesta (hecho)
Un fallo repetido en cada vuelta de la ingesta (p. ej. el 304 de RustFS de octubre de 2026) puede dejar el feed parado más de un día sin que nada «falle» a la vista. Una tarea del Cerebro
(`vigilar_motor`, cada 15 minutos; `cerebro/licitaciones/vigilante.py`) mira `/ops/status` y avisa por **correo interno** (buzón de notificaciones, solo a direcciones de la empresa): **una vez** cuando una
fuente lleva más de `vigilante.horas_sin_ingesta` (6) sin ingesta correcta, no ha completado ninguna o el motor no responde; un **recordatorio** cada `vigilante.repetir_cada_horas` (24) mientras siga; y otro aviso
**al arreglarse**. Si el correo falla, reintenta en la pasada siguiente. Se configura en `config/licitaciones.yaml` (`vigilante.destinatarios`, vacío = solo registro). El estado se guarda en `licitaciones_vigilante`.

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

### Primera versión (hecha) y lo que falta
La primera versión es **deliberadamente más sencilla** que el modelo de arriba y dice cuál es su modelo en cada resultado (`cerebro/licitaciones/simulador.py`, `POST /licitaciones/simulador`, operación `licitaciones.simular` para los
agentes y la tarjeta «Simulador de ofertas» en la ficha de la licitación; solo Dirección y Licitaciones):
- **Concursos parecidos** (adjudicaciones de los últimos 5 años en `/awards`): mismo grupo de CPV (5 cifras), zona (región, luego país, luego cualquiera) y presupuesto entre 0,5× y 2×; si hay menos de 30, se amplía y se dice cómo
  (`muestra.mercado`, avisos). De cada uno se toma la **baja del ganador** (1 − adjudicado / presupuesto base, sin IVA; solo con dato fiable y por debajo del 90 %).
- **Probabilidad de ganar con una baja b** = fracción de esos concursos en los que b habría superado la baja del ganador, **suponiendo que gana la mejor oferta económica**; con su intervalo de Wilson al 95 % (la incertidumbre). Si la
  licitación puntúa juicio de valor (criterios `SUBJ` de la ficha), se avisa de que es optimista.
- **Riesgo de baja anormal**: de los concursos cuyo ganador bajó entre b − 5 y b + 5 puntos, cuántos fueron marcados como anormales (sin dato con menos de 5). **Margen esperado** = probabilidad × (precio − coste) con el coste
  que escribe la persona; sin coste no se recomienda precio. Se recomienda el de mejor margen esperado dentro de `simulador.riesgo_anormal_max` (20 %), y pasado el primer punto con riesgo excesivo no se recomienda ninguno más agresivo.
- ***Backtesting***: cada concurso pasado se simula «a ciegas» con los demás y se mide si las probabilidades predichas coinciden con lo ocurrido (error medio de calibración). **Solo es «apto para decidir»** con al menos
  `simulador.muestra_min` (30) concursos, error ≤ `simulador.error_max` (0,10) y sin juicio de valor; si no, el resultado dice «solo orientativo». Los umbrales están en `config/licitaciones.yaml`: los fija Dirección.
- Es código determinista (la IA no calcula importes) y siempre muestra el número de datos, los rangos y los supuestos. **No decide**: el precio y presentarse son humanos.

**Reglas de puntuación del pliego (hecho)**: una persona anota en la tarjeta del simulador («Reglas de puntuación del pliego», tabla `licitaciones_reglas_precio`, `cerebro/licitaciones/reglas.py`) cómo puntúa el pliego el precio:
fórmula (proporcionalidad inversa, proporcional a la baja o lineal hasta una baja tope), puntos del precio sobre el total y, si lo fija, el umbral de baja anormal, con la nota de dónde lo dice. El agente no puede anotarlas (como el
cumplimiento de la matriz). Con ellas la curva añade los **puntos de precio** de cada oferta (frente a una rival con la baja mediana de los ganadores parecidos, que se dice) y el **riesgo de baja anormal es el umbral del pliego**
(0 por debajo, 1 desde él) en vez del estimado con el pasado; la recomendación no pasa nunca de ese umbral. Se avisa de cuánto pesa el precio (p. ej. 51 de 100).
**Coste del ERP (hecho)**: en vez de escribir el coste, se puede dar el código de un presupuesto (`Quotation`) del ERP (`cerebro/licitaciones/coste_erp.py`, solo lectura y con la política de acceso de Licitaciones). Coste = Σ cantidad × coste de
la línea (`valuation_rate`), o del artículo, o su último precio de compra; las líneas sin coste **no se inventan**: se listan, el coste se marca incompleto y el resultado nunca es «apto para decidir». POR VERIFICAR con el ERPNext real que los
artículos tengan esos campos informados.

**Todavía no hecho** (sigue en el plan de arriba): que el Analista de Pliegos *proponga* las reglas con cita para que la persona las confirme (hoy las copia ella), los competidores probables uno a uno, la puntuación técnica del Evaluador
y la simulación Monte Carlo. Con las adjudicaciones actuales no se puede conocer la distribución de **todas** las ofertas, solo la del ganador: por eso el modelo es «supera al ganador».
Con el histórico sin cargar, la muestra será corta y el simulador lo dirá (orientativo).

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
  no decide). `plataformas_contratacion` conserva `preparar_paquete` (ya no baja documentos: ver «Pliegos» más abajo).
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
Ficha básica, solo lectura); en la fase 4, Embudo, Alertas, Ficha completa y Competencia en forma de listados y ranking
(bloque «Competencia y mercado»); las fichas completas de competidor y de organismo llegan con la fase 5, y «Simular» en la 5b.

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

---
### Estado de la integración con el Cerebro (28/10/2026)
- **Herramienta `licitaciones`** (`api/cerebro/herramientas/licitaciones.py`): `buscar`, `ficha`, `novedades_desde` y `estado_motor`, solo lectura, sin
  aprobación. La tienen el Director de Licitaciones, el Rastreador y Viabilidad. Usa el token compartido del motor (`LICITACIONES_API_TOKEN`);
  Keycloak sustituirá al token cuando lo usen más clientes (SEC-031).
- **Sección «Licitaciones» del panel** (`/licitaciones`): estado del motor, últimas novedades, buscador con filtros y paginación, y ficha del expediente
  con lotes, adjudicaciones y evidencia. La pasarela (`/licitaciones-api`) comprueba el grupo del usuario y solo deja pasar lecturas.
- **Resumen de las 16:00** (28/10/2026): tarea de Celery (`resumen_licitaciones`, cola `lote`, todos los días a las 16:00 hora de Madrid) que **consulta**
  la API del motor, puntúa y ordena; **no usa el modelo de IA**. Lo que Dirección ve en el panel (`/licitaciones/resumen`, y una tarjeta en
  `/licitaciones`): lo actualizado desde las 16:00 del día anterior en los 20 CPV decididos (con sus descendientes), ordenado por **encaje** (0–100:
  CPV 40, zona 20, importe 15, plazo 15, procedimiento 10; los pesos y el perfil están en `config/licitaciones.yaml`, **POR VALIDAR con Dirección**),
  con las razones de cada puntuación, y aparte las adjudicaciones y las anulaciones. Lo que supera 1 000 000 € se cuenta pero no se detalla.
  Dice lo que no sabe: si el motor no responde guarda el resumen como «sin datos» con el motivo y reintenta cada 15 min (3 veces); si el motor no está al día
  o hay más novedades de las que se leen (500), lo avisa. Se guarda en `licitaciones_resumenes` y hay botón «Generar ahora» (últimas 24 h) por si el equipo
  estaba apagado a las 16:00. Lo ven Dirección y el departamento de Licitaciones.
  Diferencias con el ADR 0007: el motor aún no tiene `publicada_desde`, `encaje_min` ni `orden=encaje`, así que la ventana usa `actualizada_desde`
  (la fecha de la versión en origen) y el encaje se calcula en el Cerebro con los datos de la ficha; pasará al motor cuando se proyecte el encaje (§7.9).
- **Embudo propio** (hecho): la tabla `licitaciones` del Cerebro pasa a ser el embudo (`motor_id`, `encaje`, estados `detectada → en_estudio → presentada →
  ganada | perdida`, y `descartada` para el no ir; fechas de cada paso). `api/cerebro/licitaciones/embudo.py` (cálculo puro y probado), rutas
  `GET /licitaciones/embudo/resumen`, `GET /licitaciones/embudo`, `POST /licitaciones/embudo/estudiar` y `POST /licitaciones/embudo/{id}/estado`
  (Dirección y departamento de Licitaciones), pantalla `/licitaciones/embudo`, botón «Estudiar» en la ficha y bloque en el dashboard. Diferencias con el
  ADR 0007: el cambio de estado es un `POST` (la pasarela `/cerebro` solo deja pasar GET y POST); el código de expediente deja de ser único (se repite
  entre organismos) y la identidad es `motor_id`; los motivos de pérdida son una lista cerrada **POR VALIDAR con Licitaciones** (`MOTIVOS_PERDIDA`).
  Los datos de «Estudiar» los pide el servidor al motor: el navegador solo manda el identificador.
- **Consumidor de eventos** (hecho): servicio `licitaciones-eventos` (`python -m cerebro.licitaciones.consumidor`, perfil `licitaciones` del compose del Cerebro),
  consumidor duradero `cerebro-embudo` de JetStream. `licitacion.nueva` abierta, dentro del importe y con encaje ≥ `embudo.encaje_min` de
  `config/licitaciones.yaml` (60, **POR VALIDAR con Dirección**; o `LICITACIONES_ENCAJE_MIN`) → fila `detectada` del embudo. `.adjudicada`, `.formalizada` y
  `.anulada` → se anota `estado_motor` si ya está en el embudo (una `detectada` que se anula pasa sola a `descartada`; el resto lo decide la gente, el panel solo
  avisa). Nunca cambia lo que haya decidido una persona; idempotente por versión; no ejecuta agentes. El evento solo lleva la fuente y el `id_origen`: los datos se
  piden a la API del motor con el filtro nuevo `GET /tenders?fuente=&id_origen=` (hecho en el motor). Si el proyector aún no lo tiene, se reintenta (10 s, 1 min,
  5 min, 30 min, 2 h; 6 entregas). **Ojo con la carga del histórico**: sus eventos van al mismo flujo y se procesan igual (una consulta al motor por evento, casi todos
  «ignorada: no está abierta»); cuando se lleven a `LIC_HISTORICO` (ADR 0002) dejarán de pasar por aquí.
- **Alertas guardadas** (hechas, canal «panel»): búsquedas guardadas con aviso. `api/cerebro/licitaciones/alertas.py`; tablas `licitaciones_alertas` y
  `licitaciones_avisos` (UNIQUE por alerta y evento: no avisa dos veces); rutas `GET/POST /licitaciones/alertas`, `POST /licitaciones/alertas/{id}` (cambiar:
  nombre, filtro, eventos, activa), `POST /licitaciones/alertas/{id}/borrar`, `GET /licitaciones/avisos` y `POST /licitaciones/avisos/leer`; pantalla
  `/licitaciones/alertas`, «Guardar como alerta» en el buscador y tarjeta en el dashboard. Un segundo consumidor duradero, `cerebro-alertas`, en el mismo servicio
  `licitaciones-eventos`: por cada evento, para cada alerta activa que lo pida, **pregunta al motor si el expediente cumple el filtro**
  (`GET /tenders` con el filtro + `fuente` + `id_origen`; así el texto libre y todo lo demás lo evalúa quien lo entiende) y deja un aviso. Solo avisa de expedientes
  actualizados hace menos de `alertas.max_antiguedad_dias` (7) y una «nueva» solo si sigue abierta: la carga del histórico no inunda a nadie. Permisos: una personal
  es solo de su dueño (ni Dirección la ve); una de departamento la ven sus miembros y Dirección, y la crean o cambian el responsable del departamento y Dirección.
  Diferencias con el contrato `/alerts` del motor (`openapi.yaml`): viven en el Cerebro y no en el motor porque la API del motor aún no sabe quién es cada
  usuario (Keycloak en el motor, SEC-031); cambiar y borrar van por `POST` (la pasarela solo deja GET y POST); sin `If-Match` (v1); solo los criterios que el motor
  filtra hoy (texto, CPV, NUTS, comprador, estado, procedimiento, importes; no `area`, `fuente` ni `encaje_min`); las de competencia son un tipo aparte (ver abajo).
- **Alertas en el resumen de las 16:00** (hecho): una alerta de **departamento** puede tener el canal `resumen_diario`; sus avisos del periodo salen en una sección
  «Alertas de departamento» del resumen (`alertas` en el documento y `totales.alertas`; hasta `resumen.avisos_por_alerta` = 5 por alerta, el resto se cuenta). El aviso
  se guarda siempre y sigue visible en el panel: el canal solo añade el resumen. Una alerta **personal** no puede usar ese canal (el resumen lo ven Dirección y
  Licitaciones): lo rechaza el código y también la base de datos (`licitaciones_alertas_resumen_solo_departamento`). La sección sale **aunque el motor no responda** (los
  avisos ya están guardados) y, si no se pueden leer, el resumen sale igual y lo dice. Se activa por alerta desde `/licitaciones/alertas` («Incluir en el resumen»).
- **Alertas de competencia** (hecho): una alerta de `tipo = competencia` avisa cuando una licitación que cumple su filtro (CPV, zona, comprador…) **se adjudica** a uno de
  los competidores de su lista (NIF) o, con la lista vacía, a cualquiera; con **«solo empresas nuevas»** (`solo_nuevos`, solo sin lista de competidores) avisa únicamente si quien gana no había ganado antes nada en ese mercado (ver «Nuevo competidor» abajo). Solo
  avisa del evento `adjudicada` (la base lo exige: `licitaciones_alertas_competencia`), **una sola vez por expediente y alerta**, y con el mismo límite de antigüedad que las
  demás (7 días: la carga del histórico no inunda). El consumidor comprueba el filtro con el motor como siempre y luego lee la ficha (`GET /tenders/{id}`) para ver los
  adjudicatarios; el aviso (`tipo = competencia.adjudicada`) guarda en `detalle` quién ganó, por qué importe sin IVA y en qué lote. Un adjudicatario **sin NIF** no se puede comparar
  con la lista (el motor no une empresas por nombre) y solo salta si la lista está vacía; el NIF de una **persona física** no se guarda en el aviso. Los permisos, el canal
  (`panel`, `correo`, `resumen_diario` para departamentos) y la pantalla son los de las demás alertas: `/licitaciones/alertas` → «Qué vigila: Competencia».
- **Nuevo competidor** (hecho): una alerta de competencia con `solo_nuevos` avisa de una adjudicación solo si el adjudicatario (por NIF) **no tenía ninguna adjudicación anterior en el mercado de la alerta** (sus CPV y su zona; si no los
  fija, el grupo de 4 cifras de los CPV del expediente), en otra licitación y antes de esa fecha: se pregunta al motor (`/awards?adjudicatario=nif:…&adjudicada_hasta=…`). **Solo con historia suficiente:** si el motor no tiene
  adjudicaciones de hace al menos `nuevo_competidor.cobertura_meses` (12, en `config/licitaciones.yaml`), no avisa de nada —con unas semanas de datos casi cualquier empresa parecería nueva— y lo anota en el registro. Un
  adjudicatario sin NIF no se puede comparar y no cuenta; el NIF de una persona física se usa para comparar pero nunca se guarda en el aviso. El aviso lleva `nuevos: true` («empresa nueva en este mercado», en el panel y en el correo).
  **Límite conocido:** que el motor no conozca una victoria anterior (otra plataforma, antes de su histórico) no significa que no exista; por eso es una pista, no un hecho. Columna `licitaciones_alertas.solo_nuevos` (con restricción:
  solo competencia y sin competidores). Panel: casilla «Solo empresas nuevas en el mercado» al crear la alerta.
- **Alertas por correo** (hecho): el canal `correo` de una alerta (personal o de departamento) envía los avisos a una dirección `correo_destino` **de la empresa**
  (`avisos.dominios` en `config/buzones.yaml`, por ahora `101.cat`): es correo interno y automático, así que no pasa por la bandeja de aprobaciones (que es para lo que
  sale de la empresa) y una dirección de fuera se rechaza al crear la alerta, otra vez justo antes de enviar y también en la base de datos (`licitaciones_alertas_correo_destino`:
  hay dirección si y solo si el canal es `correo`). Sale del buzón `notificaciones` (sin departamentos: ningún agente lo usa; ya está en
  `config/buzones.yaml`; falta su contraseña: `python3 scripts/buzon_alta.py --id notificaciones --solo-clave` y reiniciar la API y el worker; sin clave no envía y lo dice en el
  registro). El consumidor solo deja el aviso; la tarea `enviar_avisos_correo` (`api/cerebro/licitaciones/avisos_correo.py`, cola `lote`, cada 5 minutos) manda los pendientes
  (`licitaciones_avisos.correo_enviado IS NULL`), agrupados por alerta (hasta `max_por_correo` = 20 por mensaje), con `Auto-Submitted: auto-generated`. Un fallo del servidor se
  anota (`correo_error`) y se reintenta hasta `max_intentos` = 5; un aviso de más de `max_antiguedad_horas` = 48 ya no se envía; al pasar una alerta a `correo` no se envía lo que
  ya había. El canal es único: «correo» incluye el panel pero no el resumen de las 16:00. Desde `/licitaciones/alertas`.
- **Carga del histórico segura** (hecho): los eventos de lo que se carga desde los ZIP van a su propio flujo `LIC_HISTORICO` (solo el proyector lo consume; el Cerebro no recibe millones de
  «nuevas», ADR 0002) y el relay publica antes lo en vivo. Guía para cargarlo poco a poco en un PC delicado: `docs/CARGAR_HISTORICO.md`, con `scripts/estado_historico.sh` para ver el avance.
- **Pliegos, fase 1: descarga segura y antivirus** (hecho; la fase 2 y la pantalla están justo debajo): la herramienta `pliegos`
  (`documentos` y `descargar`, `api/cerebro/licitaciones/pliegos.py`) baja un documento de una licitación **por su número en la ficha, nunca por dirección** (SEC-140): la URL sale del motor y
  se revalida (solo https, solo las plataformas de `contratacion.pliegos.hosts` en `config/integraciones.yaml` y sus subdominios, solo IP públicas, redirecciones comprobadas una a una y sin salir
  de la lista). El tipo se decide por el **contenido** (PDF, DOCX, XLSX, ODT/ODS o ZIP; un HTML, un SVG o un ejecutable se rechazan), hasta 100 MB y 40 descargas al día. Todo entra en
  **cuarentena** y solo pasa a `limpio/` si ClamAV (`clamd`, servicio `clamav` del compose, perfil `licitaciones`) lo analiza y está limpio; **falla cerrado**: sin antivirus, con firmas de más
  de 48 h, demasiado grande o cifrado, queda «no analizable» y no se ofrece; con macros de Office queda «con_macros» (solo se leerá su texto); un infectado se borra y se guarda su huella y la firma.
  **Ningún agente ni el panel recibe el fichero**, solo su estado, tamaño y SHA-256. Esto cierra la SSRF que tenía el antiguo `plataformas_contratacion.descargar_documento` (aceptaba cualquier URL
  que propusiera el modelo): esa operación se ha **quitado**. Los metadatos van en `pliegos_documentos`; los ficheros, en `/datos/licitaciones/pliegos/<licitación>/`. El Analista de Pliegos ya
  tiene la herramienta.
- **Pliegos, fase 2: leer los documentos y anotar requisitos con cita comprobada** (hecho): cuando un documento queda `limpio`, `descargar` extrae su texto **en un proceso aparte** (`python -m cerebro.licitaciones.extractor`,
  `extractor.py`): entorno VACÍO de secretos, directorio de trabajo temporal, plazo de 130 s y límites del sistema operativo puestos por él mismo (1 GB de memoria, 110 s de CPU, 32 MB como máximo por fichero escrito —las imágenes de página del OCR—, pocos ficheros). Solo lee texto:
  PDF por páginas (hasta 500), Word y OpenDocument en «bloques» de ~3000 caracteres y Excel por hojas; macros y objetos incrustados se ignoran; un ZIP no se abre. Las páginas de un PDF **sin texto seleccionable (escaneos) se leen con OCR** dentro del mismo proceso aparte (Poppler a imagen, Tesseract en español, catalán e inglés; sin shell, mismo entorno
  vacío y mismos límites; hasta 120 páginas y ~95 s por pasada, 3 a la vez): el aviso del documento dice qué páginas se leyeron con OCR (pueden tener errores, sobre todo en cifras; una cita que no coincida
  con el texto se rechaza igual) y cuántas quedaron sin leer por falta de tiempo, que revisará una persona. El texto va a `pliegos_paginas` con búsqueda en castellano. El agente tiene `leer` (una página), `buscar` (fragmentos con documento y página) y **`anotar_requisito`**: guarda un
  requisito (tipo, resumen con sus palabras, valor y **cita literal**) SOLO si esa frase está de verdad en esa página —se comparan sin mayúsculas, espacios, guiones de fin de línea ni tipo de comillas, y una cita de menos de
  20 caracteres no prueba nada y se rechaza—, así que el modelo no puede inventarse un requisito ni una página. Nacen en `borrador` (`pliegos_requisitos`): **los confirma o rechaza una persona**, nunca el agente. Todo lo que devuelve
  lleva la nota de que es texto de terceros (datos, no instrucciones). **Límite conocido:** el extractor es un proceso con límites, no un contenedor sin red (SEC-142 pide el contenedor); mientras tanto no tiene secretos que robar.
- **Pliegos, fase 3: la pantalla del expediente** (hecho): la ficha del expediente (`/licitaciones/expedientes/{id}`) tiene una tarjeta «Pliegos» (solo Dirección y Licitaciones; para los demás no aparece). Lista los documentos con su estado
  (sin descargar, limpio, con macros, no analizable, infectado), cuántas páginas, bloques u hojas se han leído y el botón «Descargar y analizar» (o «Reintentar» si no se pudo). Debajo, los **requisitos** que ha anotado el Analista de Pliegos:
  tipo, resumen, valor y la **cita literal con su lugar** («Pliego administrativo, página 12»), con «Ver la página» para comprobar la cita contra el texto leído y los botones **Confirmar**, **Rechazar** y **Volver a borrador**. Solo una persona los pulsa
  (`POST /licitaciones/pliegos/requisitos/{id}/revisar`; el agente no tiene esa operación) y queda anotado quién y cuándo. Los confirmados forman la matriz de cumplimiento. Rutas: `GET /licitaciones/pliegos/{licitación}`,
  `POST …/descargar` (`{n}`), `GET …/documentos/{n}/paginas/{p}`. Nadie recibe el fichero original.
- **Matriz de cumplimiento** (hecho): los requisitos **confirmados** forman la matriz. De cada uno, **una persona** anota si 101.cat lo cumple —`cumple`, `parcial`, `no_cumple`, `no_aplica` o `pendiente`— y,
  si es parcial o no se cumple, **por qué** (obligatorio); queda quién y cuándo (`POST /licitaciones/pliegos/requisitos/{id}/cumplimiento`; un borrador o un rechazado no se valora, y el agente no tiene
  esa operación). `GET /licitaciones/pliegos/{licitación}/matriz` da las filas con su cita y página y un resumen; `listo` solo si no queda nada pendiente, parcial ni sin cumplir y no hay requisitos en borrador sin
  revisar. Los agentes (Evaluador, Redactor…) la leen con la operación `pliegos.matriz` (solo lectura). En la ficha de la licitación, cada requisito confirmado lleva su selector y la tarjeta ofrece
  «Descargar la matriz (CSV)» (`;` como separador y sin que una celda pueda tomarse por fórmula). Columnas nuevas en `pliegos_requisitos`: `cumplimiento`, `cumplimiento_nota`, `cumplimiento_por`, `cumplimiento_en`.
- **Plazos en el calendario** (hecho): en el embudo, el botón «Añadir el plazo al calendario» (`POST /licitaciones/embudo/{id}/calendario`) crea en el calendario CalDAV de la empresa un evento
  que **termina a la hora del plazo de presentación** (dura `calendario_plazos.duracion_min` = 30 minutos), con recordatorios `recordatorios_dias` = 3 y 1 días antes y el plazo en hora local en la
  descripción. Lo crea una persona al pulsar y **sin invitados**: no sale nada de la empresa, por eso no pasa por la bandeja de aprobaciones (la que sí pasa es `calendario.crear_cita` de los agentes,
  que puede invitar a gente de fuera). Usa la cuenta `CALENDARIO_LICITACIONES_USUARIO`/`_CLAVE` o, si no, `CALENDARIO_USUARIO`/`_CLAVE`, y el calendario `calendario_plazos.calendario` (vacío = el primero
  de la cuenta; en `config/licitaciones.yaml`). El evento lleva un UID fijo sacado del expediente del motor: volver a pulsar lo **actualiza** en vez de duplicarlo. La columna
  `licitaciones.calendario_plazo` guarda qué plazo se puso: si el plazo cambia en el motor, la tarjeta avisa de que está «desfasado» y el botón pasa a «Actualizar el plazo en el calendario» (no se
  actualiza solo). «Quitar del calendario» lo borra. Al descartar, ganar o perder la licitación el evento **no se borra solo**: se quita a mano. Si el calendario no está configurado o no responde, el panel
  lo dice (503) y no se anota nada. Los textos de la licitación (títulos de terceros) se escapan como texto de iCalendar.
- **Viabilidad frente a lo que hizo la gente** (hecho): el resumen del embudo (`GET /licitaciones/embudo/resumen`) lleva un bloque `viabilidad` y el embudo del panel un cuadro
  desplegable. Cuenta, por recomendación (IR, NO IR, REVISAR), los informes **generados en el periodo** y lo que pasó después: **seguidos** (IR con la licitación presentada, o NO IR con la
  licitación descartada), **en contra** (al revés), **pendientes** (aún detectada o en estudio) y cómo han acabado (ganadas y perdidas). No dice quién «acierta»: la gente decide por motivos
  que el informe no ve, y una licitación no presentada no da resultado. Con menos de 5 licitaciones resueltas el cuadro avisa de que es pronto para sacar conclusiones. Es solo lectura
  (se calcula al pedirlo, a partir de la tabla `licitaciones`) y no cambia nada. Sirve para decidir, cuando haya datos, si el informe merece más o menos peso en el rastreo.
- **Informe de viabilidad a petición** (hecho): en el embudo, el botón «Pedir informe de viabilidad» (`POST /licitaciones/embudo/{id}/viabilidad`, 202) encola la tarea
  `pedir_viabilidad` (cola `peticiones`): Viabilidad valora esa licitación (sin los filtros del rastreo) y guarda el informe; «Volver a pedir…» lo sustituye tras confirmar
  (`reemplazar`). Solo hay una petición en curso por licitación (se da por perdida a los 20 minutos); si el modelo no responde se reintenta hasta 3 veces y, si no, la tarjeta
  muestra el error y se puede volver a pedir. Sigue siendo consultivo: no cambia el estado ni decide nada. La lista del embudo se refresca sola mientras hay una petición en curso.
- **Rastreo diario del embudo** (hecho): la tarea `rastreo_embudo` (`api/cerebro/licitaciones/rastreo.py`, cola `lote`, 06:30 según `rastreo.hora`) elige las `detectada`
  **abiertas en el motor y con plazo** (a más de `rastreo.dias_minimos_hasta_plazo` = 3 días), de más a menos encaje y hasta `rastreo.max_por_dia` = 10 (**POR VALIDAR**:
  si Viabilidad se satura, bajarlo o subir `embudo.encaje_min`), y pide a **Viabilidad** (agente `viabilidad`, modelo «juez») un informe de cada una. El informe se guarda en
  `licitaciones.viabilidad` (recomendación IR / NO IR / REVISAR leída de un cierre de formato fijo, motivo, texto, hora) y el panel lo enseña en el embudo como
  ayuda. **Es consultivo**: no cambia el estado ni `decision` (ir o no ir lo decide una persona; presentarse y firmar, también). Los datos de la licitación (título,
  organismo…) los escribe un organismo, no 101.cat: van a Viabilidad dentro de un bloque marcado como texto de terceros, recortados y sin poder cerrarlo. Nunca pisa un
  informe anterior (repetir la tarea es inofensivo), un fallo en una licitación no impide valorar las demás, y si el modelo no está disponible se reintenta (hasta 4
  veces, con espera creciente) conservando lo ya valorado. El Rastreador deja de lanzar su ejecución genérica de las 6:00 (`horario: null` en su ficha): su trabajo es esta tarea.
- **Adjudicaciones y competidores en el motor** (hecho): tabla `adjudicaciones` (una fila por lote y adjudicatario; migración 0004) derivada **siempre del `documento`** del
  expediente con una función SQL y un disparador (se regenera sola con cada versión nueva del expediente, desaparece si se anula, y la migración rellena lo que ya había).
  La API sirve `GET /api/v1/awards` (texto, CPV, NUTS, comprador, adjudicatario por UUID o `nif:`, resultado, importes, fechas, procedimiento, orden por fecha, importe o
  baja) y `GET /api/v1/competitors` (ranking de empresas del mercado: contratos, importe, **cuota** sobre el importe del mercado filtrado, baja media y mediana, tendencia
  y última adjudicación, con `muestra` = cuántas adjudicaciones hay detrás; obliga a acotar por CPV, NUTS o comprador). La **baja** (1 − adjudicado/presupuesto base, sin IVA)
  solo se calcula cuando el presupuesto es fiable: el del lote, o el del expediente si no tiene lotes; si hay varios adjudicatarios en el mismo lote, o lo adjudicado supera
  el presupuesto (contratos plurianuales: en las muestras hay uno con el cuádruple), queda vacía. Un adjudicatario se identifica por su NIF; una persona física con el NIF
  tapado, por su nombre. **Tendencia** = contratos de los últimos 12 meses frente a los 12 anteriores (`sin_datos` con menos de 3). Solo cuenta lo adjudicado en euros. La
  herramienta `licitaciones` de los agentes tiene las operaciones nuevas `adjudicaciones` y `competidores`. **Aún no**: `area`, ni el ranking de licitadores no adjudicatarios (solo se publica en las actas de la mesa).
- **Página «Competencia» del panel** (hecho): `/licitaciones/competencia` enseña el ranking de `/competitors` de un mercado que se elige con CPV, zona (NUTS) o NIF del comprador
  (más fechas y orden); la dirección de la página es la consulta, así que se puede compartir. Cada empresa muestra cuota (barra y %), contratos, importe, baja media y mediana,
  tendencia y última adjudicación, y se abre para ver sus **últimas adjudicaciones en ese mismo mercado** (`/awards` con los mismos filtros), enlazadas a la ficha de la
  licitación. Siempre dice cuántas adjudicaciones hay detrás y, con menos de 10, avisa de que las cifras son orientativas. La pasarela del panel deja pasar `awards` y
  `competitors` (solo la lista, solo lectura). Los nombres son datos de terceros: se escriben como texto, nunca como HTML.
- **Contratos que vencen** (motor, hecho): `GET /api/v1/expiring-contracts` (CPV, zona, comprador, importe mínimo, `vence_desde`/`vence_hasta`, por defecto de hoy + 3 meses a hoy
  + 12 meses y como máximo 36 meses de anchura, `con_prorrogas`). **Fecha de fin = inicio + duración prevista − 1 día**; la duración es la del lote (si la trae) o la del
  expediente; el inicio, por orden de fiabilidad, la entrada en vigor publicada (`confianza` 0,9), la formalización (0,7) o la adjudicación (0,4). Sin duración o sin inicio no hay
  fecha. Las **prórrogas** vienen en el pliego como texto libre («Cabe la opción de tres (3) prórrogas de un (1) año cada una», «Podrá ser prorrogado por un año más»…): el
  parser reconoce solo lo que se dice sin ambigüedad (cuántas y de cuánto, o que se admiten o no) y **no suma por adivinación** (dos cláusulas distintas, «hasta un máximo
  de…»); en esos casos `prorrogas_posibles` es sí/no/desconocido y el texto original va en `prorrogas_texto` para que lo lea una persona. **Limitaciones conocidas**: no
  se tienen en cuenta modificaciones posteriores del contrato ni prórrogas ya ejecutadas (la fecha es la prevista en origen); y los expedientes ingeridos antes de esta
  versión no traen el texto de las prórrogas hasta que se vuelvan a proyectar (nueva versión del expediente o repetir los eventos, ADR 0003). La herramienta de los agentes
  tiene la operación `contratos_que_vencen`.
- **Página «Contratos que vencen» del panel** (hecho): `/licitaciones/vencen` lista, agrupados por mes de fin, los contratos que terminan en un periodo (por defecto de aquí a 3 meses hasta
  dentro de 12; filtros CPV, zona, comprador, importe mínimo, fechas con tope de 36 meses —se valida antes de preguntar— y «contar las prórrogas posibles»). Cada contrato dice cuándo
  termina y **cuánto fiarse de esa fecha** (inicio publicado / calculada desde la formalización / desde la adjudicación: orientativa), quién lo tiene ahora, el importe, qué se sabe de las
  prórrogas (sin prórrogas / con prórrogas hasta tal fecha / admite sin fecha / no consta) y, desplegable, el texto del pliego tal cual (dato de un tercero: se escribe como texto, nunca como
  HTML). Avisa de que la fecha es la prevista en origen. Desde «Competencia» hay un enlace con el mismo mercado. La pasarela del panel deja pasar `expiring-contracts` (solo la lista).
- **Fichas de organismo y de competidor** (motor, hecho): `GET /api/v1/organizations/{id}` con el UUID que dan las listas, `nif:` o `dir3:` (`vat:` da 400; **nunca por nombre**).
  Un NIF o un DIR3 dan el mismo UUID que calculan las listas, y un comprador con NIF y DIR3 es una sola organización (su id es el del NIF). Una organización puede ser comprador,
  adjudicataria o las dos: `roles`, y por papel (`como_comprador`, `como_proveedor`) contratos, importe, baja media y percentiles, ofertas medias, CPV (grupos de 5 cifras), trimestres
  (los últimos 16), `muestra`, a quién adjudica y cuánto se concentra en un solo adjudicatario (`repeticion_adjudicatario`, solo comprador) o a quién vende (`principales_compradores`,
  solo proveedor). `desde`, `hasta` y `cpv` acotan las cifras pero no la existencia. Los otros nombres con que aparece son informativos y **nunca unen** organizaciones. La
  migración 0006 añade `expedientes.comprador_id` (columna generada con la misma función `lic_uuid8`) para poder buscar compradores por UUID. La herramienta de los agentes
  tiene la operación `organizacion`.
- **Página de la ficha de organización del panel** (hecho): `/licitaciones/organizaciones/{uuid}` enseña, por cada papel (comprador y/o adjudicataria), la muestra (con aviso si son menos de 10),
  contratos, importe, baja media y percentiles, ofertas por licitación, a quién adjudica (con cuánto se concentra: ≥ 50 % en un solo adjudicatario se marca como mercado muy concentrado)
  o a quién vende, en qué mercados (enlaces a «Competencia» por CPV) y una gráfica de contratos por trimestre. Los otros nombres con que aparece salen aparte y avisan de que no prueban
  que sea la misma empresa; una persona física lo dice. Filtros por periodo y CPV en la dirección. Los nombres de empresas y organismos de «Competencia», «Contratos que vencen»
  y la ficha de una licitación enlazan a su ficha. Los errores se distinguen: «esa organización no existe» (404 con datos) no es lo mismo que «el motor todavía no tiene esta función»
  (404 «La ruta no existe»: motor desactualizado, hay que reconstruir `api` y `proyector`) ni que una dirección con NIF (solo se abre por UUID). La pasarela del panel deja pasar `organizations/{uuid}` solo con UUID (nunca por nombre ni NIF desde el navegador).
- **Reprocesar expedientes antiguos** (motor, hecho): `proyector reproyectar [-simular] [-fuente F] [-limite N] [-despues ID]` (tarea de una sola vez; ver `licitaciones/README.md`) relee de `raw` el
  original de cada expediente ya proyectado y rehace su modelo de lectura con el parser actual, para que los antiguos tengan, por ejemplo, el texto de las prórrogas. Comprueba el SHA-256 de cada
  original; no resucita los anulados, no pisa un expediente que cambió mientras tanto, no toca versión, original ni fecha de actualización y es idempotente. `-simular` cuenta cuántos cambiarían sin escribir.
- Pendiente: canal `correo`; un botón «Pedir informe de viabilidad» para una licitación concreta; y llevar a Viabilidad lo que ya sabe 101.cat de cada organismo.
