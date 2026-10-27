# Procedencia — PLACSP, sindicación 1143 (contratos menores de los perfiles alojados en PLACSP)

- **Fuente**: PLACSP, conjunto «Contratos menores publicados en los perfiles del contratante ubicados en la PLACSP» (desde
  2018). **Existe y se ha verificado** (26/10/2026): feed `sindicacion_1143/contratosMenoresPerfilesContratantes.atom` y ZIP
  anuales/mensuales `contratosMenoresPerfilesContratantes_AAAA[MM].zip` (enlazados en la página del conjunto hasta 202610).
- **Página del conjunto**: https://www.hacienda.gob.es/es-es/gobiernoabierto/datos%20abiertos/paginas/contratosmenores.aspx
- **No hay feed de menores de las plataformas agregadas**: la 1044 se llama literalmente «SinMenores» y la página de Hacienda
  solo ofrece 643, 1044, 1143, encargos a medios propios y consultas preliminares. Los menores de Cataluña están en el
  conjunto Socrata `ybgg-dgi6` (ver `../cat_ybgg-dgi6/PROCEDENCIA.md`); los de las demás plataformas autonómicas
  (Madrid, Andalucía, Euskadi…) **POR VERIFICAR** en sus propios portales.
- **Descarga**: 26/10/2026 desde `contrataciondelsectorpublico.gob.es` (esta vez completó: 4,4 MB). `Last-Modified: Mon, 26
  Oct 2026 02:04:22 GMT`, `ETag: "42cb53-65eb4bf9b28cb"`. `<feed><title>`: «… DatosAbiertosMenores».
- Medido en la página completa (444 entradas): todas `RES`, `ProcedureCode=6` (contrato menor), `NoticeTypeCode=DOC_CAN_ADJ`
  (más 1 `DOC_CN` y 1 `DOC_CD`), `ResultCode=8` en todas; adjudicatario, NIF e importes con y sin IVA en el 100 %.

## Ficheros
| Fichero | Bytes | SHA-256 | Capturado (UTC) | URL | Notas |
|---|---|---|---|---|---|
| `extracto_contratosMenoresPerfilesContratantes_20261026.atom` | 149917 | `3f90c33cd8aa6014b83e2f8d4ebf3058045e9df4f278bfd4e6f664e3590f1caf` | 2026-10-26T10:33:48Z | https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1143/contratosMenoresPerfilesContratantes.atom | extracto de un original de 4377427 B, SHA-256 `cd79fa12957d0756aa253213216962e50bb42e58a5569070e3e3c20c210c230f`; página 1 |


## Entradas del extracto
| Tipo | Id | Bytes | SHA-256 del fragmento | Por qué está |
|---|---|---|---|---|
| entry | 20777550 | 8660 | `91bcecf2b7ddf0cfb2d0f2a396ba74b7410f6d48e57bd295ead6110a43327297` | menor con `TenderResult/cbc:Description` |
| entry | 20777561 | 9597 | `21427ab58970f353c6eb04058927dff4d9b210074d0d5b33c066550665c5d921` | adjudicatario `schemeName="OTROS"` |
| entry | 20778397 | 8687 | `11236b5b6830cd2f137c27f083bcaae8870fb109ce98c33b68ca9c10f6214bd8` | órgano sin DIR3 (solo NIF e ID_PLATAFORMA) |
| entry | 20778403 | 9574 | `2e660eac5d4c578bda65f2b17c14ce3e9441deeb66a232f0f4bae0e29bdffd93` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778440 | 9539 | `47ab5fe206087cca80d9f75aa668592457fdc02b0309e3c69e9a15d1d856ce9d` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778441 | 9884 | `da84fb14884b9eb13b28d4afa4d4f47ee2e080ef39d4095b4a62723d1aec1f91` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778470 | 9519 | `6cc818ce9bfab1b866bed5155940eac6d817e11b71392f251c8ccd14dfc5d069` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778471 | 9530 | `26d26d01a0b31c6fdc3cca5f7298245a86449edc7779ad63bb027875d2995c73` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778477 | 9574 | `0bcbcccde674d3eb12f4025dde759c71d457cdb64cf89788b2bba5995b108b8f` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778563 | 9357 | `b60471dda02808227a3cef601ffc9e8b25e74407fc8b9cde44e73b07105cac02` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20778581 | 9661 | `9e138a82b27106fafb97ee8f588d3b287c9351e9ee6120f5c5523aee2d2d13c3` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20776610 | 9487 | `0d046cc9df9c62f9fea0a591a4f3c04af59d10f7df973413077313962260dff0` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20777216 | 9886 | `02a532d630ca32fd2b9656d9e177d2a88e3dccb814c270cec9d1e028ba8a64e6` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20777249 | 9674 | `215ff2f1b713a482588b7c2144807de94b4e023f8181df01553faa5f49705001` | CPV propio (lista de Dirección 26/10/2026) |
| entry | 20117185 | 15708 | `6d74cb7ec3d493988394fbe6415e4bba7543eaabf4ecae7016cf681618dbd716` | menor con anuncio DOC_CN y DOC_CD (menor con publicidad previa) |

## Cómo se hizo el extracto
`python3 -I licitaciones/tools/corpus/atom_extract.py PAGINA.atom SALIDA.atom ID...` copia **byte a byte** la cabecera
original del `<feed>` (espacios de nombres, `<link rel="next">`, `<updated>`), los `<entry>`/`<at:deleted-entry>` elegidos y
el cierre `</feed>`. El SHA-256 de cada fragmento coincide con el del mismo fragmento en la página original (que no se
guarda por tamaño; se puede volver a descargar mientras la fuente la mantenga: las páginas con fecha en el nombre no
cambian, la cabeza del feed sí). El orden de las entradas es el original (de más reciente a más antigua por `<updated>`).

## Licencia y condiciones de reutilización
Ministerio de Hacienda, «Condiciones generales para la reutilización de información» del aviso legal
(https://www.hacienda.gob.es/es-ES/Paginas/Avisolegal.aspx, leído el 26/10/2026, remite a www.datos.gob.es/avisolegal):
reutilización autorizada **con fines comerciales y no comerciales** (copia, difusión, modificación, adaptación, extracción,
reordenación y combinación), con las condiciones generales de la Ley 37/2007 (no desnaturalizar el sentido de la
información; citar la fuente, p. ej. «Origen de los datos: Ministerio de Hacienda»; mencionar la fecha de la última
actualización; no sugerir participación ni patrocinio del Ministerio; conservar sin alterar los metadatos de fecha y
condiciones de reutilización). Uso bajo la propia responsabilidad; el Ministerio no garantiza la continuidad del servicio.
Las entradas contienen **datos personales públicos** (nombre y NIF de adjudicatarios que son personas físicas): solo para
pruebas; ver §5 «Datos personales» del proyecto.

## Seudonimización (26/10/2026)
El repositorio es público: en `extracto_contratosMenoresPerfilesContratantes_20261026.atom` se han sustituido datos de personas físicas (2 adjudicatarios persona física: NIF y nombre) por valores
ficticios con formato válido (DNI `99999001S`–`99999004H`, nombres «Persona Ficticia …»). El resto del archivo es
idéntico al descargado. SHA-256 del original descargado: `e38fdb21e10c7ad49f439b3740db4ab9d5b0efe88eb7bc9d2361ac4d18e846ca` (149923 bytes); el de la tabla es el del archivo seudonimizado.

## Seudonimización adicional (27/10/2026)
Revisión previa a fusionar la fase 0 en un repositorio público: se sustituyeron por valores ficticios los **nombres de personas físicas** que seguían en claro
(adjudicatarios autónomos: «Persona Ficticia Tres» a «Persona Ficticia Siete») y las **direcciones de correo con nombre de persona** de los datos de contacto
(`contacto.ficticio.NN@example.invalid`). Los correos genéricos de los órganos de contratación (contratacion@…, secretaria@…) se conservan. Los NIF de personas físicas ya vienen
enmascarados en origen (`***6795**`). El SHA-256 y el tamaño de la tabla son los del archivo seudonimizado.
Archivos afectados: el archivo .atom.
