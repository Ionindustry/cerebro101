# Inventario de campos por fuente (fase 0)

Fecha de la muestra: **26/10/2026**. Muestras y procedencia (URL, hora, SHA-256, licencia) en `licitaciones/testdata/*/PROCEDENCIA.md`.
Regla (NORMAS): solo figura como comprobado lo observado en una muestra real; lo demás va marcado **POR VERIFICAR**.

## 0. Sobre qué se ha medido

| Fuente | Muestra medida | En `testdata/` | Cómo reproducir la medida |
|---|---|---|---|
| PLACSP 643 (perfiles, sin menores) | 2 páginas completas: **567 entradas** (+1 baja); 323 `TenderResult` | página 1 entera (68) + extracto de 19 entradas y 1 baja de la página 2 | `codice_inventory.py --paths`, `codice_values.py`, `zip_scan.py` sobre las páginas (re-descargables, URL en PROCEDENCIA) |
| PLACSP 1044 (agregadas, sin menores; incluye Cataluña) | 2 páginas completas: **823 entradas** (+109 bajas); 859 `TenderResult`; 257 entradas con NUTS ES51* | extractos de 20 entradas y 3 bajas | ídem |
| PLACSP 1143 (menores de perfiles PLACSP) | 1 página completa: **444 entradas**; 444 `TenderResult` | extracto de 15 entradas | ídem |
| TED Search API v3 | 3 respuestas de búsqueda (20 + 50 + 40 anuncios, país ES) | todas | `jq`/Python sobre `ted/busqueda/*.json` |
| TED eForms (XML) | **12 anuncios**: 8 `ContractAwardNotice` (7 can-standard, 1 can-modif) y 4 `ContractNotice` (cn-standard) | todos | `eforms_inventory.py ted/eforms/*.xml` |
| Cataluña Socrata `ybgg-dgi6` | cobertura de **cada columna sobre el conjunto entero** (2 032 596 filas: 233 483 `es_agregada=NO`, 1 799 113 `SÍ`) + 71 filas de muestra + 1 JSON de detalle | todo | `coverage.json` (consulta `count(col)` agrupada) |

Notación de rutas:
- CODICE: `CFS` = `/atom:entry/cac-place-ext:ContractFolderStatus`; prefijos `cbc`/`cac` = `urn:dgpe:names:draft:codice:schema:xsd:Common{Basic,Aggregate}Components-2`; `x:`/`X:` = `cbc-place-ext`/`cac-place-ext`.
- eForms: raíz `ContractNotice` o `ContractAwardNotice` (UBL 2.3, `cbc:CustomizationID` = `eforms-sdk-1.13`/`1.14`); `EXT` = `ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/efext:EformsExtension`; `NR` = `EXT/efac:NoticeResult`; `ORG(x)` = `EXT/efac:Organizations/efac:Organization[efac:Company/cac:PartyIdentification/cbc:ID = x]/efac:Company`.
- Socrata: nombre de columna (`fieldName`) del JSON de `/resource/ybgg-dgi6.json`.
- Cobertura: CODICE «n/N entradas» (643 / 1044 / 1143) o «n/N resultados» cuando es por `TenderResult`; eForms «CAN x/8 · CN y/4»; Socrata «% no nulo NO · SÍ» sobre todo el conjunto.
- Los nº de BT de eForms son los del SDK; **solo BT-720, BT-171 y BT-193 se han leído en la documentación oficial** (docs.ted.europa.eu, «Competition Results»); el resto de números de BT: POR VERIFICAR.

## 1. Identidad, versiones y paginación

| Aspecto | PLACSP 643 / 1044 / 1143 (ATOM + CODICE) | TED | Cataluña (Socrata) |
|---|---|---|---|
| Id de origen | `atom:entry/atom:id` (URL; último segmento numérico estable por expediente) | `cbc:ID[@schemeName="notice-id"]` (UUID del anuncio) + `cbc:VersionID`; nº de publicación `EXT/efac:Publication/efbc:NoticePublicationID` (`00602980-2026`) | `id_intern` = `{uuid expediente}` o `{uuid}_{índice de lote base 0}` |
| Expediente | `CFS/cbc:ContractFolderID` (567/567, 822/823, 444/444) | `cbc:ContractFolderID` = UUID del procedimiento (12/12); nº interno `cac:ProcurementProject/cbc:ID` (12/12) | `codi_expedient` (99,8 % · 100 %) |
| Versión / fecha | `atom:updated`; **la misma entrada aparece varias veces** (en la misma página: 20344204; entre páginas: 20480621…). Spec §3.3.2: quedarse con la de `updated` mayor; §3.3.1: correcciones excepcionales **sin cambiar `updated`** → idempotencia por hash, no solo por fecha | `cbc:IssueDate`+`cbc:IssueTime`; cambios en `EXT/efac:Changes` (CN 1/4, CAN 1/8) | sin fecha de fila; `rowsUpdatedAt` global en los metadatos; fechas por fase (`data_publicacio_*`) |
| Bajas | `at:deleted-entry/@ref,@when` + `at:comment/@type` ∈ {`ANULADA`, `CERRADA`} (643: 1 ANULADA; 1044: 109 CERRADA) | n/a | `fase_publicacio='Anul·lació'` + `resultat` ∈ {Desert, Desistiment, Renúncia} |
| Paginación | `feed/link[@rel="next"]`, páginas `…_AAAAMMDD_HHMMSS.atom` y **`…_HHMMSS_1.atom`** cuando coinciden; orden descendente por `updated` (verificado en las 5 páginas). ZIP anuales y mensuales para histórico | `paginationMode: "ITERATION"` + `iterationNextToken` (verificado: 50 + 40 = 90, sin solapes; **la última página aún devuelve token**) o `page`/`limit` | `$limit`/`$offset`/`$order` (POR VERIFICAR límites) |
| Cambios condicionales | `Last-Modified` y `ETag` presentes en las páginas; respuesta 304 POR VERIFICAR | `ETag` y `Cache-Control` en el XML | POR VERIFICAR |

## 2. Licitación (expediente y lotes)

| Dato | CODICE (643 / 1044 / 1143) | Cobertura | eForms | Cob. TED | Socrata | Cob. Cat (NO · SÍ) |
|---|---|---|---|---|---|---|
| Estado | `CFS/x:ContractFolderStatusCode` (lista `SyndicationContractFolderStatusCode-2.04`: PRE, PUB=en plazo, EV=pendiente de adjudicación, ADJ, RES=resuelta, ANUL) | 567 · 823 · 444 | no hay estado; se deduce del tipo de anuncio | — | `fase_publicacio` (última fase) | 100 % · 100 % |
| Tipo de anuncio | `CFS/X:ValidNoticeInfo/x:NoticeTypeCode` (lista `TenderingNoticeTypeCode-2.11`; vistos DOC_CN, DOC_CD, DOC_CAN_ADJ, DOC_FORM, DOC_PIN, DOC_PIN_RTL, DOC_MOD, DESISTIMIENTO, ANUL_CN) + fecha `…/X:AdditionalPublicationDocumentReference/cbc:IssueDate` + medio `x:PublicationMediaName` | 566 · 823 · 444 | `cbc:NoticeTypeCode` (`cn-standard`, `can-standard`, `can-modif`, `pin-rtl`, `cn-social` en la búsqueda) + `EXT/efac:NoticeSubType/cbc:SubTypeCode` | 8/8 · 4/4 | `fase_publicacio` | 100 % |
| Objeto | `CFS/cac:ProcurementProject/cbc:Name` (+ `atom:title`, `atom:summary`) | 567 · 823 · 444 | `cac:ProcurementProject/cbc:Name`, `cbc:Description` | 8/8 · 4/4 | `denominacio`, `objecte_contracte` | 100 % / 99,9 % |
| Tipo de contrato | `CFS/cac:ProcurementProject/cbc:TypeCode` (`ContractCode-2.08`: 1 suministros, 2 servicios, 3 obras, 22, 31, 32, 7, 8, 50; en 1044 aparece **999**, que no está en la lista) + `cbc:SubTypeCode` | 567 · 823 · 444; subtipo 548 · 0 · 427 | `cbc:ProcurementTypeCode[@listName="contract-nature"]` | 8/8 · 4/4 | `tipus_contracte` | 99,9 % · 99,7 % |
| Procedimiento | `CFS/cac:TenderingProcess/cbc:ProcedureCode` (`SyndicationTenderingProcessCode-2.07`: 1 abierto, 2 restringido, 3 NSP, 4 NCP, 6 menor, 7, 8, 9 abierto simplificado, 13, 100, 999) | 567 · 823 · 444 (1143: siempre 6) | `cac:TenderingProcess/cbc:ProcedureCode[@listName="procurement-procedure-type"]` (open, restricted, neg-wo-call) | 7/8 · 4/4 | `procediment` (texto en catalán) | 89,6 % · 75,7 % |
| Tramitación | `CFS/cac:TenderingProcess/cbc:UrgencyCode` (`DiligenceTypeCode-1.04`: 1 ordinaria, 2 urgente, 3 emergencia) | 567 · 823 · 431 | `…/cac:ProcessJustification/cbc:ProcessReasonCode[@listName="accelerated-procedure"]` | 5/8 · 4/4 | `tipus_tramitacio` | 99,8 % · 51,5 % |
| Sistema (acuerdo marco, SDA) | `CFS/cac:TenderingProcess/cbc:ContractingSystemCode` (`ContractingSystemTypeCode-2.08`) | 567 · 823 · 0 | `cac:ProcurementProjectLot/cac:TenderingProcess/cac:ContractingSystem/cbc:ContractingSystemTypeCode` (`framework-agreement`, `dps-usage`) | 7/8 · 4/4 | `racionalitzacio_contractacio` | 14,0 % · 24,3 % |
| SARA / sobre umbral | `CFS/cac:TenderingProcess/cbc:OverThresholdIndicator` | 567 · 823 · 0 | implícito (está en TED) | — | — | — |
| **Valor estimado** | `CFS/cac:ProcurementProject/cac:BudgetAmount/cbc:EstimatedOverallContractAmount` (spec 4.4: art. 9 Directiva; en acuerdos marco, el de todo el AM) | 567 · 821 · 427 | `cac:ProcurementProject/cac:RequestedTenderTotal/cbc:EstimatedOverallContractAmount` (BT-27, procedimiento) / mismo bajo `cac:ProcurementProjectLot/cac:ProcurementProject/…` (lote); máximo de AM `…/EXT/efbc:FrameworkMaximumAmount` | proc. 4/8 · 4/4; lote 5/8 · 3/4 | `valor_estimat_expedient` / `valor_estimat_contracte` (lote) | 93,3 % · 0 % / 82,3 % · 66,1 % |
| **Presupuesto base sin IVA** | `CFS/cac:ProcurementProject/cac:BudgetAmount/cbc:TaxExclusiveAmount` (spec 4.4: precio máximo sin impuestos) | 567 · 822 · 444 | **no existe** en eForms (POR VERIFICAR) | — | `pressupost_licitacio_sense_1` (exp.) / `pressupost_licitacio_sense` (lote) | 94,9 % · 0 % / 88,3 % · 64,1 % |
| **Presupuesto base con IVA** | `CFS/cac:ProcurementProject/cac:BudgetAmount/cbc:TotalAmount` | 567 · **0** · 444 | no existe | — | `pressupost_licitacio_amb_1` / `pressupost_licitacio_amb`; tipo de IVA solo en el JSON de detalle (`dadesPublicacio.iva`) | 63,5 % · 0 % / 64,9 % · 53,6 % |
| Lotes | `CFS/cac:ProcurementProjectLot` con `cbc:ID[@schemeName="ID_LOTE"]`, `cac:ProcurementProject/cbc:Name`; en 643 también `BudgetAmount/TaxExclusiveAmount` y `TotalAmount`, CPV y lugar por lote; **en 1044 solo id y nombre** | entradas con lotes 145 · 143 · 0; importe por lote 145 · 0 · 0 | `cac:ProcurementProjectLot/cbc:ID[@schemeName="Lot"]` (`LOT-0001`; `LOT-0000` = sin lotes) y su `cac:ProcurementProject` | 8/8 · 4/4 | una fila por lote: `numero_lot`, `descripcio_lot` | 31,8 % · 54,2 % |
| CPV | `CFS/cac:ProcurementProject/cac:RequiredCommodityClassification/cbc:ItemClassificationCode` (8 dígitos, **sin dígito de control**, varios) | 566 · 823 · 404 | principal `cac:ProcurementProject/cac:MainCommodityClassification/cbc:ItemClassificationCode`, adicionales `…/cac:AdditionalCommodityClassification/…` (también por lote) | 8/8 · 4/4 | `codi_cpv` (**con dígito de control**, `72000000-5`; uno por fila) | 85,9 % · 88,4 % |
| NUTS / lugar | `CFS/cac:ProcurementProject/cac:RealizedLocation/cbc:CountrySubentityCode` (lista NUTS-2021; niveles mezclados: `ES`, `ES51`, `ES511`, `ESZZZ`) + `cbc:CountrySubentity`, `cac:Address/cbc:CityName`, `cbc:PostalZone` | 566 · 823 · 444 | `…/cac:RealizedLocation/cac:Address/cbc:CountrySubentityCode[@listName="nuts"]` (por procedimiento y por lote) | 8/8 · 4/4 | `codi_nuts`, `lloc_execucio` | 87,3 % · 53,7 % |
| Duración | `CFS/cac:ProcurementProject/cac:PlannedPeriod/cbc:DurationMeasure/@unitCode` (DAY, MON, ANN) o `cbc:StartDate`/`cbc:EndDate` | duración 525 · 748 · 440; fin 41 · 65 · 4 | `…/cac:PlannedPeriod/cbc:DurationMeasure/@unitCode` (MONTH, YEAR) o `StartDate`/`EndDate` (por lote) | lote 3/8 · 2/4 | `durada_contracte` (**texto libre**: «2 anys», «19/06/2026 a 31/12/2026», «15 anys»); estructurado en el JSON de detalle (`duradaTermini.anys/mesos/dies/iniciTermini/fiTermini`) | 72,5 % · 99,7 % |
| Prórrogas (previstas) | `CFS/cac:ProcurementProject/cac:ContractExtension/cac:OptionValidityPeriod/cbc:Description` y `cbc:OptionsDescription` (texto) | 202 · 0 · 0 | `…/cac:ContractExtension/cbc:MaximumNumberNumeric` (nº de renovaciones) | 2/8 · 0/4 | solo JSON de detalle (POR VERIFICAR campo) | — |
| Plazo de ofertas | `CFS/cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate` + `cbc:EndTime` | 528 · 546 · 377 | `cac:ProcurementProjectLot/cac:TenderingProcess/cac:TenderSubmissionDeadlinePeriod/cbc:EndDate`+`EndTime` (con zona) | 0/8 · 3/4 | `termini_presentacio_ofertes` | 86,5 % · 0 % |
| Criterios de adjudicación | `CFS/cac:TenderingTerms/cac:AwardingTerms/cac:AwardingCriteria/` `cbc:AwardingCriteriaTypeCode` (OBJ = automático, SUBJ = juicio de valor), `cbc:AwardingCriteriaSubTypeCode` (OBJ: 1 precio, 2 otros, 3 medioambiental, 4 social, 5 innovación; SUBJ: 01, 02, 03, 99), `cbc:Description`, `cbc:WeightNumeric`; también por lote | 502 · **0** · 0; por lote 54 · 0 · 0 | `…/cac:AwardingTerms/cac:AwardingCriterion/cac:SubordinateAwardingCriterion/cbc:AwardingCriterionTypeCode` (price, quality, cost), `cbc:Description`, peso en `EXT/efac:AwardCriterionParameter/efbc:ParameterNumeric` (`ParameterCode=poi-exa`) | 7/8 · 4/4; peso 5/8 · 2/4 | solo JSON de detalle: `criterisAdjudicacio[].criteri`, `.ponderacio` | — |
| Organismo: nombre | `CFS/X:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name` (+ jerarquía `X:ParentLocatedParty/…`) | 567 · 823 · 444 | `ORG(cac:ContractingParty/cac:Party/cac:PartyIdentification/cbc:ID)/cac:PartyName/cbc:Name` | 8/8 · 4/4 | `nom_organ` (+ `nom_ambit`, `nom_departament_ens`, `nom_unitat`) | 100 % |
| Organismo: **NIF** | `…/cac:Party/cac:PartyIdentification/cbc:ID[@schemeName="NIF"]` | 567 · **0** · 444 | `ORG(…)/cac:PartyLegalEntity/cbc:CompanyID` (`schemeName` NIF o ID_PLATAFORMA cuando lo trae; muchas veces sin `schemeName`) | 8/8 · 4/4 (con `@schemeName` 4/8 · 2/4) | no está; sí en el JSON de detalle (`organ.nif`) | — |
| Organismo: **DIR3** | `…/cbc:ID[@schemeName="DIR3"]` | 443 · 325 · 357 | no observado | — | `codi_dir3` | 97,5 % · 98,3 % |
| Organismo: id de plataforma | `…[@schemeName="ID_PLATAFORMA"]` (643, 1143) / `…[@schemeName="ID_OC_PLAT"]` (1044) | 567 · 823 · 444 | `CompanyID[@schemeName="ID_PLATAFORMA"]` (observado en anuncios enviados desde PLACSP) | — | `codi_organ` | 100 % |
| Plataforma agregadora | — · `CFS/X:LocatedContractingParty/cac:Party/cac:AgentParty/cac:PartyIdentification/cbc:ID` (62 = Generalitat de Catalunya, 661, 63, 121, 721, 561, 161) · — | 0 · 823 · 0 | — | — | — | — |
| Tipo de poder adjudicador | `CFS/X:LocatedContractingParty/cbc:ContractingPartyTypeCode` (`ContractingAuthorityCode-2.10`, 1–12) + `cbc:ActivityCode` | 567 · 0 · 444 | `cac:ContractingParty/cac:ContractingPartyType/cbc:PartyTypeCode` (ra, la, body-pl…) + `cac:ContractingActivity/cbc:ActivityTypeCode` | 6/8 · 4/4 | `nom_ambit` | 100 % |
| Fondos UE | `CFS/cac:TenderingTerms/cbc:FundingProgramCode` (NO-EU, EU, FEDER, PRTR…) | 567 · 823 · 444 | `…/cac:TenderingTerms/cbc:FundingProgramCode[@listName="eu-funded"]` | 7/8 · 4/4 | `tipus_financament` | 4,9 % · 0 % |
| Enlace al expediente | `atom:link/@href` (PLACSP: deeplink; **1044: URL de la plataforma de origen**, p. ej. `contractaciopublica.cat/ca/detall-publicacio/{uuid}/{id}`) | 567 · 823 · 444 | `…/cac:CallForTendersDocumentReference/…/cbc:URI`, `cac:BuyerProfileURI` | — | `enllac_publicacio` | 100 % |
| Enlace a TED | `CFS/cbc:UUID[@schemeName="TED"]` = `procedure-identifier` de TED (**verificado**, ver §5) + envío al DOUE `X:AdditionalPublicationRequest/cbc:AgencyID=DOUE`, `x:SendDate` | 207 · 95 · 0 | `cbc:ContractFolderID` | 12/12 | — | — |

## 3. Adjudicación, formalización y modificaciones (por lote)

CODICE: un `CFS/cac:TenderResult` por lote **y por adjudicatario** (el acuerdo marco 8259141 de 1044 trae 110). Cobertura por
`TenderResult` y `ResultCode`. 643: RC8 (adjudicado) n=155, RC9 (formalizado) n=133, RC3 (desierto) n=31, RC4 (desistimiento) n=4.
1044: RC9 n=607, RC8 n=230, RC3 n=20, RC4 n=2. 1143: RC8 n=444.
eForms: un `NR/efac:LotResult` por lote que enumera **todas** las ofertas del lote (`efac:LotTender`); el contrato
`NR/efac:SettledContract` apunta a la oferta ganadora (`efac:LotTender/cbc:ID`); oferta → `NR/efac:LotTender` →
`efac:TenderingParty` (`TPA-…`) → `NR/efac:TenderingParty/efac:Tenderer/cbc:ID` (`ORG-…`) → `ORG(…)`.

| Dato (§5 del proyecto) | CODICE | Cobertura (643 RC8 · RC9 / 1044 RC8 · RC9 / 1143) | eForms | Cob. CAN (n=8) | Socrata | Cob. Cat (NO · SÍ) |
|---|---|---|---|---|---|---|
| Resultado | `CFS/cac:TenderResult/cbc:ResultCode` (`TenderResultCode-2.09`: 8 adjudicado, 9 formalizado, 3 desierto, 4 desistimiento, 5 renuncia, 1/2/6/7/10/11 no vistos) | 100 % | `NR/efac:LotResult/cbc:TenderResultCode[@listName="winner-selection-status"]` (`selec-w`, `clos-nw`) + motivo `efac:DecisionReason/efbc:DecisionReasonCode` (`non-award-justification`) | 7/8; motivo 1/8 | `resultat` (Adjudicació, Formalització, Desert, Desistiment, Renúncia) | 75,7 % · 0 % |
| Lote | `…/cac:AwardedTenderedProject/cbc:ProcurementProjectLotID` | 85/155 · 66/133 / 129/230 · 316/607 / 0 | `NR/efac:LotResult/efac:TenderLot/cbc:ID` | 8/8 | `numero_lot` | 31,8 % · 54,2 % |
| **Adjudicatario: nombre** | `…/cac:WinningParty/cac:PartyName/cbc:Name` | 100 % en RC8/RC9 (0 en RC3/RC4) | `ORG(ganador)/cac:PartyName/cbc:Name` | 8/8 (con ganador 7/8) | `denominacio_adjudicatari` (varios con `||`) | 80,9 % · 99,7 % |
| **Adjudicatario: NIF** | `…/cac:WinningParty/cac:PartyIdentification/cbc:ID` + `@schemeName` ∈ {NIF, UTE, OTROS} | 100 % / 100 % / 100 %; esquema 643: NIF 271, OTROS 17; 1044: NIF 822, UTE 11, OTROS 4; 1143: NIF 428, OTROS 16 | `ORG(ganador)/cac:PartyLegalEntity/cbc:CompanyID` (`@schemeName` a menudo ausente) | 7/8 | `identificacio_adjudicatari` + `tipus_identificacio` (código: **542 = NIF**, verificado en el JSON de detalle; 1000019, 11162, 576, 545, 577: POR VERIFICAR; también literales NIF, UTE, NIE, VAT, DUNS) | 80,7 % · 99,6 % (tipo: 80,7 % · 0 %) |
| Pyme | `…/cbc:SMEAwardedIndicator` | 155/155 · 133/133 / 0 / 444 | `ORG(ganador)/efbc:CompanySizeCode` (large, sme, small) | 6/8 | `tipus_empresa` (PIME / No PIME) | 56,3 % · 27,3 % |
| **Importe adjudicado sin IVA** | `…/cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount` | 100 % / 227/230 · 497/607 / 100 % | `NR/efac:LotTender/cac:LegalMonetaryTotal/cbc:PayableAmount` (BT-720 «Tender Value», **incluye opciones y prórrogas**; IVA: POR VERIFICAR) | 7/8 | `import_adjudicacio_sense` (texto; varios con `||`) | 80,3 % · 99,7 % |
| **Importe adjudicado con IVA** | `…/cac:LegalMonetaryTotal/cbc:PayableAmount` | 100 % / **0 · 0** / 100 % | no existe | — | `import_adjudicacio_amb_iva` | 79,6 % · 99,7 % |
| Valor total del anuncio | — | — | `NR/cbc:TotalAmount` | 6/8 | — | — |
| **Nº de ofertas** | `…/cac:TenderResult/cbc:ReceivedTenderQuantity` (+ `SMEsReceivedTenderQuantity`, `EUNationalsReceivedTenderQuantity`, `NonEUNationalsReceivedTenderQuantity`) | 100 % / 100 % / 100 % | `NR/efac:LotResult/efac:ReceivedSubmissionsStatistics[efbc:StatisticsCode="tenders"]/efbc:StatisticsNumeric` (+ t-sme, t-oth-eea, t-no-eea, t-esubm) | 7/8 | `ofertes_rebudes` (JSON de detalle: `totalOfertesRebudes`, `numeroEmpresesConvidades`) | 58,6 % · 21,7 % |
| **Oferta más baja / más alta** | `…/cbc:LowerTenderAmount`, `…/cbc:HigherTenderAmount` (sin IVA según el ejemplo de la spec 4.35; POR VERIFICAR) | 76/155 · 95/133 / **0** / **0** | `NR/efac:LotResult/cbc:LowerTenderAmount`, `…/cbc:HigherTenderAmount` | 2/8 | no existe | — |
| **Baja anormal** | `…/cbc:AbnormallyLowTendersIndicator` («se han excluido ofertas por anormalmente bajas»; spec 4.35) | 47/155 · 34/133 / 0 / 0 | no observado (POR VERIFICAR) | 0/8 | no existe; JSON de detalle `dadesPublicacioLot[].ofertaAdjudicatariaIncursa` | — |
| **Fecha de adjudicación** | `…/cac:TenderResult/cbc:AwardDate` («fecha del acuerdo», spec 4.35) | 100 % / **0** / 100 % | `NR/efac:SettledContract/cbc:AwardDate` (decisión) — **no** `cac:TenderResult/cbc:AwardDate`, que vale `2000-01-01` en 4/8 | 6/8 | `data_adjudicacio_contracte` | 81,8 % · 99,7 % |
| **Fecha de formalización** | `…/cac:TenderResult/cac:Contract/cbc:IssueDate` (+ nº de contrato `cac:Contract/cbc:ID`) | 48/155 · 133/133 / 81/230 · 607/607 / 88/444 | `NR/efac:SettledContract/cbc:IssueDate` (+ `efac:ContractReference/cbc:ID`) | 7/8 | `data_formalitzacio_contracte` | 55,6 % · 0 % |
| Entrada en vigor | `…/cac:TenderResult/cbc:StartDate` (spec 4.35.7) | 9/155 · 75/133 / 0 / 0 | no observado | — | JSON de detalle `duradaTermini.iniciTermini` | — |
| **Fin del contrato** | no hay campo de adjudicación: `PlannedPeriod/EndDate` (raro) o `StartDate` + `DurationMeasure` (cálculo) | ver §2 | `…/cac:PlannedPeriod/cbc:EndDate` (lote) o duración | 1/8 | `durada_contracte` (texto) / JSON `fiTermini` | — |
| Motivación | `…/cac:TenderResult/cbc:Description` | 155/155 · 133/133 / 0 / 19/444 | — | — | — | — |
| Subcontratación | `…/cac:TenderResult/cac:SubcontractTerms/cbc:Rate` | 1 resultado | `NR/efac:LotTender/efac:SubcontractingTerm/…` | 7/8 | JSON de detalle `subcontractacio` | — |
| **Modificación** | `CFS/cac:ContractModification/` `cbc:ID` (nº), `cbc:ContractID`, `cac:ContractModificationLegalMonetaryTotal/cbc:TaxExclusiveAmount` (importe de la modificación), `cac:FinalLegalMonetaryTotal/cbc:TaxExclusiveAmount` (importe tras modificar), `cbc:ContractModificationDurationMeasure`, `cbc:FinalDurationMeasure`, `cbc:Note` (**`PRORROGA`** en 3: las prórrogas ejecutadas llegan como modificaciones) | 10/567 · **0/823** (1044 trae DOC_MOD sin el bloque) · 0/444 | `EXT/efac:ContractModification/` `efbc:ModifiedContractIdentifier`, `efac:ChangeReason/cbc:ReasonCode` (`modification-justification`), `efbc:ChangeDescription`; importe en BT-720 del anuncio can-modif | 1/8 | `fase_publicacio='Execució'` (otro conjunto, «fase d'execució», no muestreado) | — |
| Desierto / desistimiento / renuncia | `ResultCode` 3 / 4 / 5 + `NoticeTypeCode` DESISTIMIENTO / RENUNCIA | 643: RC3 31, RC4 4; 1044: RC3 20, RC4 2 | `TenderResultCode=clos-nw` + `DecisionReasonCode` | 1/8 | `resultat` + `data_publicacio_anul` | 8,3 % · 0,6 % |
| Recursos | `CFS/cac:TenderingTerms/cbc:ReceivedAppealQuantity` | 164/567 entradas | `NR/efac:LotResult/efac:AppealRequestsStatistics/efbc:StatisticsNumeric` | 3/8 | — | — |
| Licitadores no adjudicatarios | no existe | — | `NR/efac:LotTender` de cada oferta + `efac:TenderingParty`; en 604884 las 9 ofertas aparecen con `PayableAmount=0` salvo la ganadora | 7/8 | no existe | — |

## 4. TED Search API v3 (campos de búsqueda comprobados)
Todos los campos pedidos en `ted/busqueda/consulta_*.json` fueron aceptados: `publication-number`, `notice-type`,
`publication-date` (`2026-10-01+02:00`), `buyer-name` (objeto por idioma), `buyer-country` (`ESP`), `classification-cpv`
(lista, con repeticiones), `place-of-performance` (NUTS y país mezclados), `notice-identifier`, `procedure-identifier`,
`notice-version`, `winner-name`, `winner-identifier`, `tender-value` (lista de **cadenas**), `total-value` (número),
`result-value-notice`, `organisation-identifier-buyer`, `contract-nature`, `procedure-type`, `deadline-receipt-tender-date-lot`,
`estimated-value-lot`, `received-submissions-type-val` y `links` (`xml.MUL`, `pdf`, `html` por idioma).
Sintaxis de consulta usada: `buyer-country=ESP AND classification-cpv IN (…) AND notice-type IN (…) AND publication-date>=AAAAMMDD`.
**`classification-cpv IN (72000000)` incluye descendientes**: 10 de 20 resultados no tenían ningún CPV exacto de la lista.

## 5. Reconciliación verificada (identificadores oficiales)
| Par | Clave | Evidencia |
|---|---|---|
| PLACSP 643 ↔ TED | `CFS/cbc:UUID[@schemeName="TED"]` = `procedure-identifier` de la búsqueda = `cbc:ContractFolderID` del eForms; además el nº de expediente PLACSP aparece en el XML | `12b24802-ba60-4e0b-931c-87d324f5ef43`: entrada PLACSP (página 1 de 643, `CS/99/1126059886/26/AM`) ↔ TED 738381-2026 (`ted/busqueda/reconciliacion_uuid_placsp.json`). Los otros 2 UUID probados aún no estaban en TED (publicación reciente) |
| PLACSP 1044 (Cataluña) ↔ Socrata | UUID de `atom:link` (`contractaciopublica.cat/ca/detall-publicacio/{uuid}/{id}`) = prefijo de `id_intern` (`{uuid}_{lote base 0}`) | entrada 20132500 ↔ 2 filas de `reconc_1044_20132500.json`: mismo expediente `252/2026`, NIF, importes sin IVA y nº de ofertas por lote |
| Organismo PLACSP ↔ Cataluña | DIR3 (`schemeName="DIR3"` ↔ `codi_dir3`) | POR VERIFICAR con un caso cruzado |

## 6. Contratos menores
- **PLACSP**: feed propio **1143** (`sindicacion_1143/contratosMenoresPerfilesContratantes.atom` + ZIP desde 2018) solo para
  perfiles **alojados en PLACSP**. Mismo CODICE; `ProcedureCode=6`; `DOC_CAN_ADJ`; adjudicatario, NIF, importes con/sin IVA y
  `AwardDate` al 100 %; sin lotes, criterios ni ofertas mín./máx.; CPV 404/444.
- **Agregadas**: no hay feed de menores (la 1044 es «SinMenores»).
- **Cataluña**: en Socrata `ybgg-dgi6`: 1 353 661 filas `procediment='Contracte menor'` como «Publicació agregada de contractes»
  (`es_agregada='SÍ'`: sin `resultat`, `tipus_identificacio`, plazos ni fechas de publicación por fase; con adjudicatario,
  importes y `data_adjudicacio_contracte` al 99,7 %) + ~22 000 menores publicados individualmente (`es_agregada='NO'`).
- Otras comunidades: POR VERIFICAR (fuera de PLACSP).

## 7. Andorra
Ver `testdata/andorra/PROCEDENCIA.md`: plataforma oficial `contractacio.govern.ad` (exportación XLSX del Registre de
contractes, 2 514 contratos, sin NIF ni CPV) y BOPA; **sin licencia de reutilización** (el aviso legal prohíbe el tratamiento
informático y el uso comercial sin autorización escrita). No se guardan datos.

## 8. Sorpresas y calidad de datos (para los parsers)
1. **1044 es un CODICE reducido**: sin `AwardDate`, sin importe con IVA (`PayableAmount`), sin ofertas mín./máx., sin baja
   anormal, sin criterios, sin `TotalAmount` del presupuesto, sin NIF del organismo (solo `ID_OC_PLAT` y DIR3 en 325/823) y
   lotes sin importe ni CPV. El «Resumen de contenido» oficial (21/12/2023) dice que Agregadas sí trae «Fecha del Acuerdo» e
   «Importe con impuestos»: **contradice lo observado** en 859 resultados. Para Cataluña, Socrata completa esos huecos.
2. 1044: `TypeCode=999` y `ProcedureCode=999` (otros); acuerdo marco con 110 `TenderResult` y `BudgetAmount/TaxExclusiveAmount=0`.
3. Versiones repetidas de la misma entrada en la misma página y entre páginas; ordenar por `updated` y deduplicar por hash.
4. `atom:summary` con formatos distintos por plataforma («6.897.246,40 €» frente a «205211.31 EUR»): no parsear importes de ahí.
5. TED: `cac:TenderResult/cbc:AwardDate = 2000-01-01` en 4/8 (marcador); `CompanyID` basura (`CONTRATISTA`, `..`, `115294.0`),
   enmascarado (`****5314*`) o DNI de persona física; ofertas perdedoras con valor 0; `tender-value` como cadenas en la API.
6. Socrata: `codi_cpv` con dígito de control; varios adjudicatarios e importes concatenados con `||` (también en `tipus_empresa`);
   `tipus_identificacio` con códigos numéricos; `durada_contracte` en texto libre; filas con `fase_publicacio='Formalització'` y
   `resultat='Desert'` (ordenar con `DESC` pone los nulos primero); `valor_estimat=0.00` en concesiones demaniales.
7. Cadencia: la cabeza de 643 llevaba ~15 h sin cambios (Last-Modified domingo 19:03 UTC, leída lunes 10:35 UTC); 1044 y 1143
   se regeneraron a las 03:00. «Cada hora» (§3 del proyecto): POR VERIFICAR entre semana.
8. El host del enlace de Hacienda (`contrataciondelsectorpublico.gob.es`) es muy lento o corta la conexión; `contrataciondelestado.es`
   (el de los `rel="next"`) respondió en segundos.
9. Fragmento `<entry>` + declaraciones de espacios de nombres de la raíz basta para reparsear: 1 944 fragmentos de las 5 páginas,
   0 fallos (punto POR VERIFICAR del ADR 0004 → comprobado).

## 9. POR VERIFICAR
- Si BT-720 (TED) y `Lower/HigherTenderAmount` (CODICE) incluyen o no IVA; significado exacto de `LowerTenderAmount` en
  RC9 frente a RC8.
- Baja anormal en eForms; fecha de entrada en vigor en eForms; presupuesto base en eForms.
- Códigos `tipus_identificacio` 1000019, 11162, 576, 545, 577 (Socrata) y licencia de Cataluña (página fuera de la lista blanca).
- Límites de tasa de TED y Socrata; respuestas 304 de PLACSP con `ETag`/`If-Modified-Since`.
- Fin del contrato y prórrogas ejecutadas en 1044 (DOC_MOD sin `ContractModification`).
- Cobertura de 643/1044 en ZIP mensuales antiguos (los campos marcados (1)–(5) en el resumen oficial solo existen tras ciertas fechas).
- Menores de plataformas autonómicas distintas de Cataluña.
