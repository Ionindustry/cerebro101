# Seguridad y cumplimiento

## Aprobaciones

| Nivel | Ejemplos | Quién decide | Voz |
| --- | --- | --- | --- |
| Libre | Analizar, resumir, clasificar, borradores internos | El agente | — |
| Simple | Enviar a clientes, publicar, responder reseñas | Responsable del departamento | Sí |
| Doble | Pagos, facturas, contratos, precios, licitaciones | Responsable + dirección, dos personas distintas | No, solo panel |
| Prohibido | Borrar datos, cambiar permisos, firmar, validar documentos del ERP | Solo personas | — |

Cualquier acción con impacto externo pasa por la bandeja aunque la ficha del agente diga «libre».

## Datos y servicios externos

| Servicio | Sensibilidad máxima | Alternativa local |
| --- | --- | --- |
| Grok | Baja (temas públicos) | — |
| Jev | Media, solo con retención cero y anonimización (`USAR_JEV_NUBE=true`) | jeff o modelo local |
| Agent Reach | Baja, contenedor aislado, sin cookies personales | — |
| ScrapeGraphAI | Baja; respeta robots.txt y espacia las visitas | Funciona con modelo local |

Personas (RRHH) no usa ningún servicio externo.

## Integraciones

Correo, calendario y contratación pública se conectan directamente desde el Cerebro, sin plataformas
intermedias: todo el tráfico queda en el mismo registro de auditoría. Cada departamento usa su propia cuenta
técnica de correo y calendario, con acceso solo a su buzón. La lectura de correo es de solo lectura (no marca
mensajes como leídos), los borradores se guardan en la carpeta de borradores del departamento y el envío
requiere aprobación. Los mensajes comerciales llevan siempre el pie de baja.

Las ofertas de licitación no se presentan automáticamente: el Cerebro prepara el paquete y la lista de
comprobación, y una persona firma y presenta en la plataforma.

## Evidencias para ENS e ISO 27001

Cada petición deja una traza en Langfuse (servidor propio, los datos no salen de la empresa), agrupada por
conversación (`session`) y por persona (`user`; las tareas programadas, como `agente:<id>`):

| Qué se registra | Dónde | Contenido |
| --- | --- | --- |
| Cada paso del grafo | Observaciones `enrutar`, `elegir_agente`, `ejecutar_agente`, aprobaciones | Orden, duración, quién lo pidió |
| Cada llamada a un modelo | Observaciones `ollama.chat:<clase>` y `ollama.embed` | Modelo, texto de entrada y de salida, tokens, duración, error |
| Cada intento de usar una herramienta | Observaciones `herramienta:<nombre>.<operación>` | Agente, departamento, argumentos, resultado, si estaba aprobada y si se rechazó (herramienta no instalada, operación que exige aprobación) |
| Quién aprobó qué, cuándo y por qué canal | Tabla `aprobaciones` (PostgreSQL) | Persona, decisión, canal, comentario |
| Cada acción ejecutada | Tabla `registro_acciones` (PostgreSQL) | Acción, agente, resultado |

Correspondencia orientativa con ISO/IEC 27001:2022 (confirmar con el auditor): 8.15 registro de actividad,
8.16 actividades de supervisión, 5.28 recogida de evidencias, 5.33 protección de registros.

Cómo se usa como evidencia: en Langfuse, filtrar por fecha, persona, sesión o por observaciones con error
(`level = ERROR`); un rechazo de «operación que exige aprobación» demuestra que el control funciona.

Configuración y límites:

- `LANGFUSE_REGISTRAR_CONTENIDO=false` guarda solo metadatos (modelo, tokens, duración, agente) y sustituye los
  textos por «[contenido no registrado]»; útil si los prompts pueden llevar datos personales que no deben
  conservarse. Por defecto se guarda todo.
- La retención se fija por proyecto en Langfuse (Ajustes → Retención de datos). Hay que alinearla con la política
  de conservación de registros y con la normativa de protección de datos.
- Langfuse no es un registro inalterable: quien tenga acceso de administración puede borrar trazas. Restringid
  esos accesos, haced copia de seguridad de los volúmenes `langfuse-db`, `langfuse-clickhouse` y `langfuse-minio`,
  y exportad periódicamente lo que deba conservarse.
- Si Langfuse está parado, el Cerebro sigue funcionando pero sin trazas; conviene vigilar su disponibilidad como
  parte de la monitorización (agente Tecnología).
