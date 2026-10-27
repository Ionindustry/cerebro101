# ADR 0004 — Almacenamiento de originales: MinIO (API S3) en el propio servidor

- **Estado**: Aceptado, con dos puntos **POR VERIFICAR** (imagen de MinIO mantenida y forma exacta de la entrada en PLACSP)
- **Fecha**: 26/10/2026
- **Autor**: arquitecto del motor · **Aprueba**: responsable del motor
- **Relacionados**: 0003 (evidencia y recuperación), `docs/SEGURIDAD.md` del motor (modelo de amenazas, en curso)


> **Actualización (decisión del propietario):** el almacén del motor pasa de MinIO a **RustFS** (Apache 2.0, S3 escrito en Rust, mantenido).
> Motivo: la imagen de MinIO que usamos está congelada y sin parches. El código no cambia (habla S3 estándar con un cliente S3). Siguen
> **POR VERIFICAR**: etiqueta/`@sha256` exacta de la imagen, y que Object Lock (cubo `raw` creado con bloqueo) y la escritura condicional
> `If-None-Match` se comporten igual; las pruebas de integración de CI contra RustFS lo comprueban en cada cambio. Donde este ADR dice «MinIO»,
> léase «el almacén S3 (RustFS)»; las políticas IAM por servicio hay que revisarlas contra la API de RustFS antes de producción.

## Contexto
- §12.5: originales inmutables en S3 con SHA-256, URL, fecha de captura, versión del parser y licencia; clave
  `raw/{fuente}/{año}/{mes}/{id}/{sha256}.xml`.
- §1 del proyecto: MinIO en el propio servidor, buckets `raw` y `processed`, versionado, cifrado, Object Lock; cambiar a
  AWS S3 debe ser solo configuración.
- El Cerebro ya tiene un MinIO (`langfuse-minio`) con una imagen **congelada sin parches** (`bitnamilegacy/minio`,
  ver `docker-compose.yml`): MinIO dejó de publicar imágenes de la edición comunitaria en Docker Hub en 2025.
- Volumen estimado (POR VERIFICAR con `docs/FUENTES.md`): ~30 KB por entrada de PLACSP sin comprimir, 3 000–10 000 entradas
  al día → 100–300 MB/día sin comprimir (XML: ~10 % comprimido); ZIP mensuales del histórico ~90–100 MB por fuente y mes
  → ~12 GB para 5 años de 643 y 1044. Pliegos: solo bajo demanda (§7.6).

## Opciones
| Criterio | A. MinIO propio del motor | B. Reutilizar `langfuse-minio` | C. Garage / SeaweedFS | D. AWS S3 (nube) |
|---|---|---|---|---|
| Object Lock + versionado (requisito §12.5) | Sí | Sí, pero el bucket debe crearse con bloqueo | Garage: no tiene Object Lock; SeaweedFS: POR VERIFICAR | Sí |
| Aislamiento de credenciales y fallos | Total | Comparte administrador con Langfuse | Total | Total |
| Imagen con parches | **POR VERIFICAR** (ver «Decisión») | No (congelada) | Sí | n/a |
| Datos fuera del servidor | No | No | No | Sí (coste, dependencia externa, datos personales de autónomos en la nube) |
| RAM | ~0,5–1 GB | 0 adicional | menor | 0 |
| Compatibilidad API S3 con el SDK Go | Completa | Completa | Parcial (Garage) | Referencia |

## Decisión
**A. Un MinIO propio del motor (`licitaciones-minio`)**, separado del de Langfuse, accedido solo por la API S3 (el código
usa `aws-sdk-go-v2`, nunca la API de administración de MinIO; cambiar a AWS S3 = cambiar endpoint y credenciales).

**Imagen (POR VERIFICAR en la fase 1)**: no se usa una imagen congelada. Orden de preferencia: (1) imagen oficial o de un
distribuidor mantenido con parches de seguridad, fijada por *digest*; (2) si no existe, construir el binario desde una
etiqueta `RELEASE.*` fijada en nuestra CI (`go build`, imagen *distroless*). Si ninguna es viable, se reabre este ADR con
SeaweedFS como alternativa (comprobando Object Lock).

### Buckets
| Bucket | Contenido | Versionado | Object Lock | Ciclo de vida |
|---|---|---|---|---|
| `raw` | Originales exactos (entradas, páginas, ZIP, anuncios TED) | Sí (lo exige Object Lock) | **GOVERNANCE, 5 años** de retención por defecto (= histórico §5; POR VALIDAR con Legal) | Sin caducidad por ahora; revisión al cumplir 5 años |
| `processed` | Registro normalizado JSON por versión de parser | Sí | No (regenerable) | Versiones no actuales: borrar a 30 días; prefijos de parsers retirados: borrar a 90 días |
| `docs` | Pliegos y anexos descargados bajo demanda, **ya analizados por el antivirus** | Sí | No | Etiqueta `seguido=false` (expediente descartado o cerrado) → borrar a 365 días |
| `quarantine` | Documentos recién descargados, pendientes de antivirus | No | No | Borrar a 7 días |
| `snapshots` | *Snapshots* de OpenSearch y volcados del grafo (ADR 0003) | No | No | Conservar 14 diarias |

Los nombres se configuran por variable (`LIC_S3_BUCKET_RAW`…) porque en AWS deben ser únicos en el mundo.

**GOVERNANCE y no COMPLIANCE**: COMPLIANCE no se puede levantar ni con la cuenta raíz; si Legal ordena borrar datos de una
persona física (RGPD) o un original resulta ser malware, no habría forma. GOVERNANCE solo se levanta con el permiso
`s3:BypassGovernanceRetention`, que tiene únicamente la credencial `lic-admin`, guardada fuera del servidor; cada uso queda
registrado y requiere un ADR o una orden escrita de Legal.

### Claves (§12.5)
| Objeto | Clave |
|---|---|
| Entrada o anuncio | `raw`: `{fuente}/{año}/{mes}/{id}/{sha256}.xml` |
| Página ATOM descargada (evidencia de la descarga) | `raw`: `{fuente}/_paginas/{año}/{mes}/{dia}/{sha256}.xml` |
| ZIP mensual del histórico | `raw`: `{fuente}/_zip/{año}/{mes}/{sha256}.zip` |
| Registro normalizado | `processed`: `{fuente}/{version_parser}/{año}/{mes}/{id}/{sha256_original}.json` |
| Documento de un expediente | `docs`: `{tender_uuid}/{sha256}.{ext}` (`quarantine` igual hasta pasar el antivirus) |

- `{fuente}`: `placsp`, `placsp_agregadas`, `ted`, `cat`, `placsp_menores`.
- `{año}/{mes}`: de la **fecha de actualización en origen** de la entrada (determinista: la misma entrada da la misma clave
  aunque se capture otro día); si la fuente no la trae, la fecha de captura.
- `{id}`: id de origen normalizado a `[A-Za-z0-9._-]` (lo demás → `_`, máximo 200 caracteres); si no cabe o es ambiguo,
  `h-` + 32 primeros hex del SHA-256 del id de origen. El id exacto va siempre en los metadatos.
- `{sha256}`: de los **bytes originales sin comprimir**.
- Entrada de PLACSP: se guarda el fragmento `<entry>…</entry>` exacto tal como venía en la página (desplazamientos de
  `encoding/xml.Decoder.InputOffset`) y, en metadatos, los espacios de nombres de la raíz para poder reparsearlo; la página
  completa queda en `_paginas/`. POR VERIFICAR con el corpus que el fragmento basta para reparsear.

### Metadatos obligatorios de cada objeto de `raw`
`x-amz-meta-sha256`, `-url-origen`, `-capturado-en` (RFC 3339, UTC), `-fuente`, `-id-origen`, `-licencia` (condiciones de
reutilización de la fuente), `-etag-origen` (si lo hay), `-pagina-sha256` (para entradas), `-ingestor-version`.
La versión del parser va en `processed` (no en `raw`, que es anterior a parsear).

### Escritura
- `PUT` con `If-None-Match: *` (no sobrescribir); si ya existe, se comprueba el `sha256` de los metadatos y se sigue.
- Compresión: el cliente guarda con `Content-Encoding: gzip` (XML ~10:1); el SHA-256 y la clave son de los bytes sin
  comprimir, así que la evidencia se reproduce exacta.
- Subidas *multipart* en *streaming* para los ZIP (sin cargarlos en memoria).

### Cifrado
- En reposo: **disco del servidor cifrado (LUKS)** como base, más SSE-S3 de MinIO con clave propia
  (`MINIO_KMS_SECRET_KEY`, generada al instalar y guardada en el gestor de contraseñas con el `.env`). Sin la clave, las
  copias no se pueden leer: se documenta en el procedimiento de restauración.
- En tránsito: dentro de la red interna de Docker, HTTP; si algún día el S3 está fuera del servidor, TLS obligatorio.
- La réplica externa (ADR 0003) va cifrada en el destino.

### Credenciales por servicio (mínimo privilegio, políticas IAM de MinIO)
| Usuario | Permisos |
|---|---|
| `lic-ingestor` | `raw`: `PutObject`, `GetObject`, `HeadObject` (sin `Delete`, sin `PutObjectRetention`); `processed`: `Put/Get` |
| `lic-proyector` | `raw` y `processed`: solo lectura; `snapshots`: escritura (volcados del grafo) |
| `lic-api` | `docs`: solo lectura (servir pliegos al panel). El historial y la evidencia (clave, hash, URL) salen de las proyecciones, no de S3 |
| `lic-documentos` (descarga bajo demanda) | `quarantine`: `Put/Get/Delete`; `docs`: `Put` |
| `lic-opensearch` | `snapshots`: lectura y escritura bajo `opensearch/` |
| `lic-copias` | lectura de todo (réplica externa) |
| `lic-admin` | administración y `BypassGovernanceRetention`; **no la usa ningún servicio** |

Ningún servicio recibe la clave raíz de MinIO. La consola web de MinIO no se publica.

## Consecuencias
- Un servicio más (`licitaciones-minio`, límite 1 GB de RAM) y disco: estimación primer año 50–100 GB con histórico
  (POR VERIFICAR); alerta al 80 % del volumen.
- Object Lock obliga a crear `raw` con bloqueo desde el principio (no se puede activar después en MinIO): se hace en la
  migración de la fase 1.
- Los borrados de `raw` son excepcionales y quedan fuera del alcance de los servicios.

## Cómo se revisará
- Fase 1: confirmar la imagen de MinIO y el fragmento `<entry>`; medir crecimiento real (GB/día) y ajustar la estimación.
- Legal: validar la retención de 5 años y el uso de GOVERNANCE.
- Reabrir si no hay imagen mantenida, si el disco crece > 2× la estimación o si se decide sacar el motor a otro servidor/nube.
