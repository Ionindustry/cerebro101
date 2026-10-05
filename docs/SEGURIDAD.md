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

## Anonimización antes de enviar a Jev (nube)

Nada sale hacia Jev sin pasar por `cerebro/anonimizacion.py`. Jev solo devuelve una elección, una puntuación o un
sí/no (nunca texto libre), así que no hace falta deshacer la sustitución y la tabla de equivalencias no se conserva.

| Capa | Qué hace | Fiabilidad medida |
| --- | --- | --- |
| 1. Entidades conocidas | Clientes, proveedores y empleados de ERPNext (más `config/anonimizacion.yaml`), sin tildes ni mayúsculas, con el nombre y los apellidos sueltos y sin la forma jurídica (SL, SA) | Alta, si la lista está al día |
| 2. Datos con formato | DNI/NIE, CIF, IBAN, tarjeta (Luhn), Seguridad Social, correo, teléfono, matrícula, código postal, IP, URL y dominios, direcciones, fecha de nacimiento | Alta |
| 3. Nombres libres | Tratamientos (Sr., Dña.), presentaciones («me llamo…»), iniciales, secuencias de mayúsculas. Opcional: spaCy (`ANONIMIZACION_NER=spacy`) | Media: falla con nombres en minúsculas y sin ninguna pista |
| 4. Verificación | Se vuelve a analizar el resultado; si queda algo reconocible, no se envía | — |

Cada dato se sustituye por una etiqueta coherente dentro del texto: `[PERSONA_1]`, `[IBAN_1]`, `[DIRECCION_1]`…

**Se bloquea (no sale nada y decide el modelo local)** cuando: falta la lista del ERP estando ERPNext configurado,
el texto supera `max_caracteres`, aparece una categoría especial del RGPD (salud, ideología y creencias, datos
penales, menores; palabras y prefijos en `config/anonimizacion.yaml`), quedan datos reconocibles tras sustituir, o
las opciones llevan datos personales. El resultado de la herramienta indica `via`: `jev (anonimizado)` o
`local (no apto para la nube)`.

**Auditoría.** En Langfuse queda el texto ya anonimizado que se envió, con su huella SHA-256, el número de
sustituciones por tipo y los motivos de cada bloqueo (observaciones `jev.decidir` y `jev.decidir:bloqueado`).
Nunca se guarda el texto original ni los datos sustituidos.

**Medición.** `python scripts/evaluar_anonimizacion.py --corpus evaluacion/<conjunto>.yaml` mide la cobertura con
textos sintéticos en castellano y catalán. Los resultados, incluida la **primera medición honesta** de cada
conjunto antes de ajustar el detector, están en `evaluacion/README.md`. La cobertura sobre textos nuevos fue
claramente inferior a la del conjunto con el que se desarrolló el detector: medid siempre con textos que no hayáis
usado para ajustarlo, y ampliad los conjuntos con casos reales (sin datos reales en el repositorio).

**Límites.**
- Seudonimizar no es anonimizar. El contexto puede identificar a alguien aunque se quite el nombre. Esto reduce el
  riesgo; no sustituye al contrato de encargado de tratamiento con TypeSafe, a la retención cero confirmada por
  escrito ni a la evaluación de vuestro asesor de protección de datos.
- No detecta nombres en minúsculas sin ninguna pista («habló con pepe»), ni referencias indirectas («el alcalde de
  un pueblo de 300 habitantes»). Las categorías especiales se detectan por palabras: una redacción distinta puede
  escaparse. Para más cobertura, activad spaCy o pasad una segunda lectura con el modelo local.
- La lista de entidades depende de ERPNext: sin ERPNext solo se usan las de `config/anonimizacion.yaml`.
- Los datos de Personas (RRHH) y todo lo de sensibilidad alta no deben ir nunca a Jev: la política ya los desvía a
  Jeff o al modelo local, y la anonimización es una segunda barrera.

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

### Protección de las evidencias

| Medida | Qué hace | Dónde |
| --- | --- | --- |
| `registro_acciones` de solo anexado | Cada acción aprobada que se ejecuta (también las que fallan) deja una fila; no se puede modificar, borrar ni vaciar | Disparadores en `db/esquema.sql`; escritura en `grafo/nodos.py` |
| `aprobaciones` con historial | No se borran, no se pueden quitar decisiones y una aprobación ya resuelta no cambia de estado | `db/esquema.sql` |
| Registro libre desactivado | Nadie se da de alta solo en Langfuse (`AUTH_DISABLE_SIGNUP`); los usuarios los crea un administrador | `docker-compose.yml` |
| Roles en Langfuse | Auditores e inspectores: rol **Viewer** (solo lectura, no pueden borrar trazas). Administración, solo a quien deba gestionarlo | Langfuse → Ajustes → Miembros |
| Exportación con huellas | `scripts/exportar_evidencias.py` genera un paquete por periodo con `manifiesto.json` y `SHA256SUMS`; `--verificar` demuestra que no ha cambiado | `scripts/` |
| Copias de seguridad | `scripts/copia_seguridad.sh` copia las dos bases PostgreSQL y los volúmenes de Langfuse con sumas de control | `scripts/` |

Paquete para una auditoría:

```bash
docker compose exec api python /app/scripts/exportar_evidencias.py --desde 2026-10-01 --hasta 2026-10-31 --salida /tmp/ev
docker compose cp api:/tmp/ev ./evidencias/2026-10
python scripts/exportar_evidencias.py --verificar evidencias/2026-10     # «Integridad correcta»
```

Guardad el `manifiesto.json` (o su huella) en un sitio distinto del servidor, por ejemplo un correo firmado o el
gestor documental: así se puede demostrar después que los ficheros no se han tocado.

### Roles de la base de datos

| Rol | Quién lo usa | Puede |
| --- | --- | --- |
| `cerebro` (propietario, superusuario) | Solo el servicio de un solo uso `migraciones` y las copias de seguridad | Crear el esquema, las tablas del grafo, el rol y los permisos |
| `cerebro_app` | API, worker y beat | Leer y escribir datos de trabajo. Sobre `registro_acciones`, solo leer y anexar. Sobre `aprobaciones`, no borrar |

`cerebro_app` no es superusuario, no puede crear ni borrar tablas, ni quitar o desactivar disparadores, ni crear
roles, ni vaciar (`TRUNCATE`) las tablas de evidencias. `docker compose up` ejecuta `migraciones` antes que la
API en cada arranque (es idempotente: aplica el esquema, crea las tablas del grafo y concede los permisos,
incluidas las tablas nuevas). La API no recibe `POSTGRES_PASSWORD`; su `DATABASE_URL` se construye con
`CEREBRO_APP_PASSWORD`.

Comprobación (sale con código 1 si algún permiso no es el esperado; no deja datos):

```bash
docker compose exec api python /app/scripts/comprobar_permisos.py
```

Límite: el contenedor de la API sigue recibiendo el resto de variables de `.env` (claves de Langfuse, de ERPNext,
etc.). Para afinar más, sustituid `env_file` por una lista explícita de variables por servicio.

### Límites y tareas que quedan a vuestro cargo

- **Retención de Langfuse.** La retención configurable por proyecto es una función de la licencia Enterprise de
  Langfuse; sin ella, las trazas se conservan indefinidamente. Si la política de conservación o la protección de
  datos exigen borrar a partir de cierta fecha, hay que adquirir esa licencia o borrar periódicamente (tras
  exportar el periodo). `LANGFUSE_REGISTRAR_CONTENIDO=false` reduce el riesgo si los textos pueden llevar datos
  personales: guarda solo metadatos (modelo, tokens, duración, agente).
- **El propietario de la base de datos puede saltarse los disparadores** (`cerebro`, superusuario). Por eso la
  aplicación no lo usa: ver «Roles de la base de datos». Quien tenga la contraseña de `POSTGRES_PASSWORD` sigue
  pudiendo alterar las evidencias, así que guardadla fuera del servidor de aplicación y limitad quién la conoce.
- **Langfuse no es inalterable.** Un administrador puede borrar trazas. Por eso se exporta cada periodo con
  huellas y se guardan copias fuera del servidor.
- **Copias.** Probad la restauración cada cierto tiempo (volcado: `zcat cerebro.sql.gz | psql`). La copia de
  ClickHouse y MinIO solo es consistente con `--parar`. El volumen `ollama` (modelos) no se copia: se vuelve a
  descargar.
- Si el registro de una acción falla (base de datos caída), la acción ya se ha ejecutado: queda un error
  `NO SE PUDO REGISTRAR…` en el log de la API. Conviene alertar sobre ese texto.
- Si Langfuse está parado, el Cerebro sigue funcionando pero sin trazas; vigilad su disponibilidad
  (agente Tecnología).
