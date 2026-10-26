# Procedencia — TED (Search API v3 y anuncios eForms)

- **Búsqueda**: `POST https://api.ted.europa.eu/v3/notices/search` (sin clave), cuerpo JSON con `query` (sintaxis experta),
  `fields`, `limit`, `page` o `paginationMode: "ITERATION"` + `iterationNextToken`. Las consultas exactas enviadas se guardan
  junto a cada respuesta (`consulta_*.json`).
- **Anuncios**: `GET https://ted.europa.eu/en/notice/{número}/xml` (eForms UBL 2.3; `Content-Disposition:
  attachment; filename="2026-OJS169-00602980.xml"`, `ETag`, `Cache-Control: max-age≈43000`).
- **Fecha**: 26/10/2026. Cabeceras de la búsqueda sin información de límites de tasa (POR VERIFICAR los límites reales).
- `User-Agent: 101cat-licitaciones-corpus/0.1 (+https://101.cat)`.

## Ficheros
| Fichero | Bytes | SHA-256 | Capturado (UTC) | URL | Notas |
|---|---|---|---|---|---|
| `busqueda_ES_nuestrosCPV_20261001.json` | 93013 | `cd6366a7b576d047834587039660b55ca64969b18edddbb85c59149205499150` | 2026-10-26T10:34:08Z | https://api.ted.europa.eu/v3/notices/search | original íntegro; POST con `consulta_busqueda_ES_nuestrosCPV_20261001.json` |
| `busqueda_ES_cpv_seguridad_trafico_iter1.json` | 262936 | `8d46a7231e3f800eb414374173b152db710597f306f1a9d2821d7fb62024f946` | 2026-10-26T10:34:36Z | https://api.ted.europa.eu/v3/notices/search | original íntegro; POST con `consulta_busqueda_ES_cpv_seguridad_trafico_iter1.json` |
| `busqueda_ES_cpv_seguridad_trafico_iter2.json` | 207413 | `e3ddf6a0f096bfa2bfa42a275d6a5d28bb8a11bba115f585beb7d07eedf9e320` | 2026-10-26T11:04:44Z | https://api.ted.europa.eu/v3/notices/search | original íntegro; POST con `consulta_busqueda_ES_cpv_seguridad_trafico_iter2.json` (iterationNextToken) |
| `reconciliacion_uuid_placsp.json` | 4741 | `217dbc0252a3922f0c81c576976184b1f9061d0a1698e657c678b23b6a384f19` | 2026-10-26T10:55:25Z | https://api.ted.europa.eu/v3/notices/search | original íntegro; POST con `consulta_reconciliacion_uuid_placsp.json` |
| `602980-2026.xml` | 25289 | `771b074e898bb5cd5a77f61f2ec7ef637a76b92e87be618b3bf51497747d416e` | 2026-10-26T10:52:54Z | https://ted.europa.eu/en/notice/602980-2026/xml | original íntegro |
| `604884-2026.xml` | 44955 | `d68d666b1de9a03a87b65a3eec6a75dfe5508b7ccaea62d0cb3f678a0e5ab480` | 2026-10-26T10:52:58Z | https://ted.europa.eu/en/notice/604884-2026/xml | original íntegro |
| `610695-2026.xml` | 13457 | `c586b630e97d09deca51289afc86445dccba1a6f8ec03a4487bd704b804e85da` | 2026-10-26T10:53:02Z | https://ted.europa.eu/en/notice/610695-2026/xml | original íntegro |
| `634191-2026.xml` | 69863 | `7adae191d0183d3925881f237b063a0d8538725e31625173d703782e0632c1af` | 2026-10-26T10:52:50Z | https://ted.europa.eu/en/notice/634191-2026/xml | original íntegro |
| `645693-2026.xml` | 16911 | `5ee60a022bd30b33c49b4c30feb02a4ee6faac2ac9a1ada5c96ee656019d21bf` | 2026-10-26T10:53:00Z | https://ted.europa.eu/en/notice/645693-2026/xml | original íntegro |
| `650664-2026.xml` | 26763 | `1e9ca2995fba591a7e217cda0e82a95c14829917c73b99ecf1afebdda22f2a76` | 2026-10-26T10:52:59Z | https://ted.europa.eu/en/notice/650664-2026/xml | original íntegro |
| `652787-2026.xml` | 16981 | `0cc5c7643442e152297e3610ffab983b206731c3b957947c9a252fd2af9daf7e` | 2026-10-26T10:52:51Z | https://ted.europa.eu/en/notice/652787-2026/xml | original íntegro |
| `662840-2026.xml` | 24860 | `42afc91f8934110cbf87afe103dd57617ec0a56323004545b1ea88be47e0a526` | 2026-10-26T10:52:55Z | https://ted.europa.eu/en/notice/662840-2026/xml | original íntegro |
| `663510-2026.xml` | 32679 | `233a08a3d9378a0c1abbaa299946de633d9f4b0145a2a054d0454f5d38412be2` | 2026-10-26T10:52:56Z | https://ted.europa.eu/en/notice/663510-2026/xml | original íntegro |
| `674346-2026.xml` | 17325 | `62945bba29012d5a754ae4d71b940034ec942fe98cbd22423d4d6859b947c438` | 2026-10-26T10:52:53Z | https://ted.europa.eu/en/notice/674346-2026/xml | original íntegro |
| `675574-2026.xml` | 19718 | `07ec4726ec04968822ba762d8ce5b926dfc6eb76fb5bfaa8610e6e0ef035ce95` | 2026-10-26T10:53:03Z | https://ted.europa.eu/en/notice/675574-2026/xml | original íntegro |
| `738381-2026.xml` | 40369 | `0248cba4b78b4887741b4ba0d881d99ba083510fc60043ebe4ebedaf03f1edad` | 2026-10-26T10:56:28Z | https://ted.europa.eu/en/notice/738381-2026/xml | original íntegro |

### Qué contiene cada anuncio eForms
| Anuncio | Tipo | Interés |
|---|---|---|
| 634191-2026 | cn-standard | 5 lotes, Madrid (ES300), CPV propios |
| 652787-2026 | cn-standard | **Cataluña (ES511)**, 1 lote, CPV propio |
| 674346-2026 | cn-standard | CPV 72267000 (IZFE, Gipuzkoa) |
| 738381-2026 | cn-standard | **mismo expediente que la entrada PLACSP 643 con `cbc:UUID schemeName="TED"`=`12b24802-…`** (en `../placsp_643/licitacionesPerfilesContratanteCompleto3_20261026T103532Z.atom`) |
| 602980-2026 | can-standard | adjudicatario con NIF (ELECNOR SEGURIDAD), ofertas mín./máx. (`LowerTenderAmount`/`HigherTenderAmount`), CCTV |
| 662840-2026 | can-standard | adjudicatario con NIF (INETUM ELECTRONIC SECURITY), beneficiario final (`UltimateBeneficialOwner`) |
| 663510-2026 | can-standard | 2 lotes, UTE como adjudicataria (`U93933893`), ofertas mín./máx.; un `CompanyID` = `..` |
| 604884-2026 | can-standard | 9 ofertas de lote (`LotTender`) con `PayableAmount` 0 salvo la ganadora; `CompanyID` `115294.0` (número convertido a decimal) y `U00007761` |
| 650664-2026 | can-standard | identificador del ganador = literal `CONTRATISTA` (dato basura en origen) |
| 645693-2026 | can-standard | lote sin ganador (`clos-nw`, motivo `chan-need`) |
| 675574-2026 | can-standard | CPV 72262000/72267000; un `CompanyID` con forma de DNI de persona física |
| 610695-2026 | can-modif | modificación de contrato (`efac:ContractModification`); `CompanyID` **enmascarado** `****5314*` (persona física) |

## Licencia
Aviso legal de TED (https://ted.europa.eu/en/legal-notice, leído el 26/10/2026): «Unless otherwise noted, the procurement
notices published in the Supplement to the Official Journal of the European Union can be **freely reused, for commercial or
non-commercial purposes**» (Decisión de la Comisión 2011/833/UE). El contenido editorial de los sitios, CC BY 4.0.
Los anuncios pueden contener nombres de personas físicas (adjudicatarios, beneficiarios finales).

## Seudonimización (26/10/2026)
El repositorio es público: en `eforms/675574-2026.xml` se han sustituido datos de personas físicas (1 `CompanyID` con formato de DNI (el nombre es de una S.L. y se conserva)) por valores
ficticios con formato válido (DNI `99999001S`–`99999004H`, nombres «Persona Ficticia …»). El resto del archivo es
idéntico al descargado. SHA-256 del original descargado: `05b66a0617788e7e4b3549c0206d6c00e4128d8aa0b5544f45ef83d5ebaf8c9a` (19718 bytes); el de la tabla es el del archivo seudonimizado.
