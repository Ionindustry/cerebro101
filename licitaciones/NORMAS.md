# Normas del equipo del motor de licitaciones

Todo lo que se hace en `licitaciones/` cumple estas normas. El proyecto completo está en `docs/PROYECTO_LICITACIONES.md`;
las normas generales del repositorio, en `docs/CONTRIBUIR.md` (un PR = un cambio, CI en verde, sin secretos).

## Forma de trabajar
- **Un PR por entrega**, pequeño y legible en 10 minutos. Los agentes del equipo no hacen commits ni `push`: entregan los cambios
  en el árbol de trabajo y un informe; el responsable revisa, valida y sube.
- Cada decisión de arquitectura importante va en un **ADR** (`licitaciones/adr/NNNN-titulo.md`: contexto, opciones, decisión,
  consecuencias, cómo se revisará).
- Documentación y mensajes en **castellano**; identificadores del código en inglés, como en §12.8 del proyecto
  (`cmd/api`, `internal/connectors`…).
- **No inventar**: un campo, una URL o un comportamiento de una fuente solo se da por bueno si se ha comprobado con una muestra
  real (guardada en `testdata/` con su procedencia). Lo no comprobado se marca «POR VERIFICAR».

## Calidad
- Go estable actual, `go vet`, `staticcheck` y `gofmt` sin avisos; `golangci-lint` en CI.
- Pruebas: unitarias con tabla, **pruebas de contrato** de cada parser contra el corpus real, pruebas de integración con
  contenedores efímeros. Ningún parser se cambia sin una muestra que lo justifique.
- Errores con contexto (`fmt.Errorf("…: %w", err)`), nunca silenciados; `context.Context` en toda E/S, con plazo.
- Dependencias mínimas y fijadas (`go.sum`); revisar licencia y mantenimiento antes de añadir una.

## Seguridad
- **XML hostil**: los datos vienen de terceros. Sin entidades externas ni DTD (sin XXE), límite de tamaño y de profundidad,
  `encoding/xml` en *streaming*. ZIP: límite de descompresión (bombas ZIP) y rutas saneadas (*zip slip*).
- **Salidas a internet solo a fuentes en lista blanca** (PLACSP, TED, Cataluña) con TLS verificado; nada de URL arbitrarias
  sin pasar por los controles anti-SSRF (no IP privadas ni de bucle, redirecciones revalidadas), como la herramienta `web` del Cerebro.
- Documentos (pliegos): solo se extrae texto, antivirus antes de guardarlos, nunca se ejecutan.
- **Secretos** solo en variables de entorno/`.env` (nunca en el código, los logs ni los mensajes de error); credenciales de
  MinIO, NATS, grafo y OpenSearch distintas por servicio y con **mínimo privilegio** (el ingestor escribe en `raw`, la API solo lee).
- API: tokens de Keycloak validados (firma, emisor, audiencia, caducidad), autorización por rol y departamento en cada endpoint,
  límites de tasa, tamaño de página máximo, consultas a OpenSearch y al grafo **parametrizadas** (nunca concatenar texto del usuario).
- Ningún servicio escucha fuera de la red interna salvo lo que publique el proxy. Contenedores sin root y con sistema de ficheros
  de solo lectura cuando sea posible.
- Datos personales (adjudicatarios autónomos): minimización, sin exportaciones masivas, registro de accesos.

## Rendimiento
- Objetivos (SLO §9 del proyecto): búsqueda p95 < 100 ms, ficha p95 < 75 ms, vecindad del grafo p95 < 50 ms.
  **Se miden** (k6, `pprof`), no se suponen; cada PR que toca la ruta caliente trae su medida antes/después.
- Memoria constante en la ingesta (*streaming*), *workers* acotados, clientes HTTP reutilizados con *keep-alive*, escrituras por lotes.
- Nada de S3 ni del grafo en la ruta de búsqueda: proyecciones precalculadas en OpenSearch/Redis.
- **Presupuesto de recursos**: el servidor también ejecuta el Cerebro y Ollama. Todo contenedor del motor lleva límites de
  memoria y CPU; ninguna prueba de carga se lanza sin ellos.
- Colas con límites (`MaxAckPending`, caducidad, *dead-letter*) y métricas de retraso: nunca una cola sin vigilancia.

## Datos
- Idempotencia: (fuente, id de origen, hash). Repetir una ingesta no duplica.
- Original inmutable en S3 con SHA-256, URL, fecha de captura, versión del parser y licencia.
- Nunca fusionar entidades por nombre: organismos por DIR3/NIF, empresas por NIF.
- Importes siempre con moneda, impuestos y significado (valor estimado, presupuesto base, adjudicado).
