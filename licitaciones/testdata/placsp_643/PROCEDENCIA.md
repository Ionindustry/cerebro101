# Procedencia — PLACSP, sindicación 643 (perfiles del contratante, sin menores)

- **Fuente**: Plataforma de Contratación del Sector Público (Ministerio de Hacienda), conjunto «Licitaciones publicadas en los
  perfiles del contratante ubicados en la PLACSP, excluyendo los contratos menores».
- **Página del conjunto**: https://www.hacienda.gob.es/es-es/gobiernoabierto/datos%20abiertos/paginas/licitacionescontratante.aspx
- **Formato**: ATOM (RFC 4287) con CODICE 2 (`cac-place-ext:ContractFolderStatus`), paginación RFC 5005 (`rel="next"`),
  bajas con `at:deleted-entry` (RFC 6721). Especificación oficial: «Formato de sindicación y reutilización de datos…»,
  versión del 17/09/2024 (https://contrataciondelestado.es/datosabiertos/especificacion-sindicacion.pdf, SHA-256
  `e18e3aa19a1570965ca0d7fe906a54760f9ec032ae1a155fd0ecb3006b14f192`, no se guarda en el repositorio).
- **Descarga**: `curl` con `User-Agent: 101cat-licitaciones-corpus/0.1 (+https://101.cat)`, TLS verificado, 26/10/2026.
  Host usado: `contrataciondelestado.es` (el que aparece en los `rel="next"`). El host del enlace de Hacienda,
  `contrataciondelsectorpublico.gob.es`, sirvió a ~5 KB/s y cortó la descarga a los 300 s (1,3 de 1,97 MB): **hallazgo**.
- Cabeceras de la página 1: `Last-Modified: Sun, 25 Oct 2026 19:03:16 GMT`, `ETag: "1e11c9-65eaedda686fa"` (útiles para
  `If-None-Match`/`If-Modified-Since`; POR VERIFICAR que el servidor responda 304).

## Ficheros
| Fichero | Bytes | SHA-256 | Capturado (UTC) | URL | Notas |
|---|---|---|---|---|---|
| `licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom` | 1970633 | `c15cf7144811345e9f547cc9b4a86e9054831bdc8c84481bdb830ca81ddb0da4` | 2026-10-26T10:35:32Z | https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom | original íntegro; página 1 (cabeza del feed) |
| `extracto_licitacionesPerfilesContratanteCompleto3_20261025_200314.atom` | 751476 | `be8625b6e7b5f2739adfe56dd3f9eaa08bd5febb5f2cb83e725aa7841af796a5` | 2026-10-26T10:36:17Z | https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_20261025_200314.atom | extracto de un original de 14803061 B, SHA-256 `809daf8a57348c1bfed874c5f804ea3b2003357a3f6763a1b928ab358d24b6bc`; página 2 (rel=next de la 1) |

- La página 1 (cabeza del feed) se guarda **entera** (68 entradas): sirve de prueba de paginación (`rel="next"` →
  `…Completo3_20261025_200314.atom`) y de muestra realista. La página 2 (14,8 MB, 499 entradas + 1 baja) se recorta.
- `<feed><updated>` de ambas páginas: `2026-10-25T20:03:14.004+01:00`; las entradas van de 2026-10-25T19:51 (p1) a
  2026-10-23T14:25 (p2), ordenadas de forma descendente. La muestra cruza el cambio de hora (+02:00 → +01:00).

## Entradas del extracto de la página 2
| Tipo | Id | Bytes | SHA-256 del fragmento | Por qué está |
|---|---|---|---|---|
| deleted-entry | 20757390 | 206 | `0a5113a0de79eae34222c857fff4ea54f5880c2450211a3838cfa117cef2b520` | `at:deleted-entry` con `at:comment type="ANULADA"` |
| entry | 19035397 | 63871 | `8e7f221045121448be7e42be07daff54175e348d6ff3d96f4c5d892a3531e15b` | CPV propio; RES; formalizado (RC 9) con `StartDate`; anuncio previo con reducción de plazos (DOC_PIN_RTL); DOUE |
| entry | 19938808 | 29682 | `ea03271445a2e5e275bf305ed7e14070817799f9bb810dbd0c9bbc2d3594fed1` | adjudicatario con `schemeName="OTROS"` |
| entry | 20777887 | 16434 | `ef609d18e642b9224ea27b3f92690da6aca6a590f7396297060f5d0e2bca309c` | estado PRE (DOC_PIN_RTL) |
| entry | 18154899 | 64440 | `1e24622cef873aa6e8475afe0f4cb8957b5288d35843b980cd07dfacfd7d10fd` | 3 lotes con resultados mixtos (RC 9, 8, 8) |
| entry | 20777896 | 19542 | `a9efff2c753d5df1105376d5860190f97d323338cda1cca84c5cfe7d9aaec5eb` | CPV propio; ADJ; 1 lote |
| entry | 19861985 | 62073 | `9405fe95e10e6800bdb215fa60e03d2ee6e8f73a811847a16779986963f760f3` | 8 lotes; baja anormal `true` en un lote; NIF; importes con y sin IVA; ofertas mín./máx. |
| entry | 19799097 | 57549 | `4f234f28bbecc045e35bc9e364027fe4676a0c686fd667a6d27f9f0d0b9bce99` | CPV propio; 2 lotes formalizados |
| entry | 20344204 | 29972 | `fc88401b1b4448b30a73b97897103d3125af2d61606f68044a63b1a0e6da7c1c` | **dos versiones del mismo expediente en la misma página** (ADJ y EV): prueba de deduplicación por `updated` |
| entry | 20768070 | 18791 | `5597adbd7b2fba46dcbe0a334e36b11a7ef08e6d22a28c25dbc2caf864135400` | DESISTIMIENTO (RC 4) |
| entry | 13855381 | 26232 | `9dda02de8ef822beffd1a25dc1e5a30c5f2dc92b5030d7c04b03d589361ef69b` | modificación de contrato con `Note=PRORROGA` (prórroga como modificación) |
| entry | 15026089 | 67561 | `8349ff27736dc58c63b507cdfca2f0674fe1e947a399b59690e77a148ab74be1` | varias modificaciones (DOC_MOD) y anuncio previo |
| entry | 20480621 | 28524 | `68c87f1d171e1cb52cdedd11cc0d24faa83d4a2baffbe81ec5d506db907a5e2a` | versión EV de un expediente cuya versión RES (desierto) está en la página 1: versiones entre páginas; Cataluña (ES511) |
| entry | 20255876 | 18043 | `17b3ace51c807848730f04e7ec24b91450d496657b0f94cd389b9360693c2f53` | Cataluña (ES511), ADJ |
| entry | 20767323 | 30966 | `604bfa8a2b99d473bca2d15239b48a0504addaee77be433c58422cdf9606600d` | CPV propio; PUB; 3 lotes |
| entry | 19550912 | 77756 | `58b426377a2a623664bf6a52ea10bd1e5f868db1dcd2257d16b6463f494a89d1` | CPV propio; EV; 6 lotes; anuncio previo |
| entry | 20415893 | 52593 | `99aea02f5b32469139f4b0416066c1eeba1d32e717392d73d0099128db563d1c` | Cataluña (ES511-513); 4 lotes con desiertos (RC 3) y adjudicado (RC 8) |
| entry | 20767361 | 41699 | `6c7140d3821bd8c0bc0088138b971531026d337759698aeedfcd165aa7a879f7` | CPV propio; 4 lotes adjudicados (RC 8) |
| entry | 20344204 | 26116 | `a4ea7415ccc778f6135f75a4bf7bdee6fe2beb2e8ff1a942189647acf2482051` | **dos versiones del mismo expediente en la misma página** (ADJ y EV): prueba de deduplicación por `updated` |
| entry | 20657821 | 17628 | `d5ced04c59265abe0b8663a05bb4f0525101f2533862dde4154bbc2cd183b06d` | CPV propio; desierto (RC 3) |

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
