# Procedencia — PLACSP, sindicación 1044 (plataformas agregadas, sin menores)

- **Fuente**: PLACSP, conjunto «Licitaciones publicadas en la Plataforma mediante mecanismos de agregación, excluyendo los
  contratos menores» (desde 2016). Incluye las plataformas autonómicas: en la muestra, `AgentParty/PartyIdentification/ID`
  = 661 Junta de Andalucía, **62 Generalitat de Catalunya**, 63 Gobierno Vasco, 121 Comunidad de Madrid, 721 Gobierno de
  Navarra, 561 Xunta de Galicia, 161 Gobierno de La Rioja.
- **Página del conjunto**: https://www.hacienda.gob.es/es-es/gobiernoabierto/datos%20abiertos/paginas/licitacionesagregacion.aspx
- **Formato**: igual que 643 (ATOM + CODICE), pero con un **perfil reducido** (ver `licitaciones/docs/INVENTARIO_CAMPOS.md`).
- **Descarga**: 26/10/2026, host `contrataciondelestado.es`, mismo `User-Agent`. El primer intento contra
  `contrataciondelsectorpublico.gob.es` terminó con `Connection reset by peer`.
- La página 2 se llama `…_20261024_030059.atom` y su `rel="next"` es `…_20261024_030059_1.atom`: **cuando varias páginas
  comparten marca de tiempo se añade un sufijo `_N`**; el conector no debe deducir nombres, solo seguir `rel="next"`.

## Ficheros
| Fichero | Bytes | SHA-256 | Capturado (UTC) | URL | Notas |
|---|---|---|---|---|---|
| `extracto_PlataformasAgregadasSinMenores_20261026.atom` | 165177 | `4a7661b8336f75451c668902d7e5665c88498d7280af175fe09c56bbb81db85b` | 2026-10-26T10:35:32Z | https://contrataciondelestado.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores.atom | extracto de un original de 3410633 B, SHA-256 `8607d2d4448f42db4f0321cb9b44d9755dff30102b4f3c9afaf99e432163c14a`; página 1 |
| `extracto_PlataformasAgregadasSinMenores_20261024_030059.atom` | 161835 | `85ae242bf7f671d6142b737d4530f9c7fa9d20d4a86201359478403b1abe2312` | 2026-10-26T10:36:35Z | https://contrataciondelestado.es/sindicacion/sindicacion_1044/PlataformasAgregadasSinMenores_20261024_030059.atom | extracto de un original de 4391757 B, SHA-256 `7846983a58ea0ee78491901f91e94b0576ff31702dc4cf0a461a2cdc47be41d8`; página 2 |


## Entradas de los extractos
Página 1 (`extracto_PlataformasAgregadasSinMenores_20261026.atom`; la página original tiene 323 entradas y 109 bajas `CERRADA`):
| Tipo | Id | Bytes | SHA-256 del fragmento | Por qué está |
|---|---|---|---|---|
| deleted-entry | 8415027 | 206 | `7195657d4d81d95ba66e3fd3e0841dfeeee0fc73bada77725ef1e1e2d1e2f32f` | `at:deleted-entry` `CERRADA` |
| deleted-entry | 3565574 | 206 | `81f343ddedbbca92f1237f68cc1e249194321d21d09eb7d36b870f4be397331f` | `at:deleted-entry` `CERRADA` |
| deleted-entry | 3935293 | 206 | `a4710af7d3b7b6489000ef2f15c60992733b0620ccd0ba9db662c63d358316c3` | `at:deleted-entry` `CERRADA` |
| entry | 20777541 | 9285 | `b4a9fb3a3e50bce497e4ab719a80a78743d91ef94be9c43eac42cbf9904abbd7` | Cataluña (AgentParty 62); PUB; 6 lotes (sin importe ni CPV por lote) |
| entry | 12697452 | 12444 | `3e8be8979bf10ab625352fdf6ce56b162a1d9a29272c34643a857bd5ea7296b9` | Andalucía (661); CPV 72000000; 2 lotes formalizados; adjudicatario UTE (`schemeName="UTE"`); DIR3 + ID_OC_PLAT |
| entry | 20776575 | 7319 | `87f8b05a0b36a2bb6710c21d561457a9dd0dca10765b528d794a390244d4014b` | Cataluña; CPV propio; PUB |
| entry | 20132500 | 11169 | `12661a6ad6a62a5c8899e2fa76013a6cf5ebaf9e3132b996d0524f375ad8c69e` | Cataluña; ADJ; 2 lotes con NIF; reconciliado con Socrata (`reconc_1044_20132500.json`) |
| entry | 17667790 | 17077 | `70db1dba7f1f717947c645353ea5d200c3f3fc3d633635ece7f502e1bec17212` | País Vasco/Euskadi (ES213); modificaciones (DOC_MOD) sin bloque `ContractModification` |
| entry | 20558219 | 10613 | `e496150e61dccf0b11db3b09e9f5b00fb12b43940e61965ec86dfd280040f9d3` | anulación de anuncio de licitación (ANUL_CN); CPV propio |
| entry | 19701168 | 9084 | `8248b27f72d46b9017b81183cd97ad46403b3b0817c936294b7e200876e2f580` | Cataluña; CPV propio; ADJ |
| entry | 20430229 | 7847 | `6862ebf332c6455d1a42d0a7e4a92f72f4e4d8f491283a05d542f7f0b4ac7825` | Cataluña; DESISTIMIENTO (RC 4) |
| entry | 19295219 | 28064 | `13f430e414d759f2edb82fa78107db166b8f970d475028af07e5fb719f6b4373` | Cataluña; 10 lotes adjudicados |
| entry | 20772605 | 8642 | `fca3e236fc134a9dee50f61f6daa1113109b8a7b0b4547c4c71f2419ef1e51ad` | Cataluña (ES511); CPV propio; ADJ |
| entry | 20772609 | 9125 | `e5ae63efb18e3d865d498e04507afb6ceda2971814e163ad6afba7e333252ed0` | adjudicatario `schemeName="OTROS"` |
| entry | 20733903 | 9855 | `127f70e4cfe3e8ef12975bcd425ff7ea607d7e8669cd7c7a851d90faadb3b134` | Cataluña (ES512); CPV propio; formalizado |
| entry | 20258698 | 7074 | `7195cd4ddfbef31add04e29ac332d42c4861dff83e37a966e4bc07694fb319f3` | Cataluña; desierto (RC 3) solo con DOC_CN |
| entry | 20115765 | 15381 | `a4fb5fab7fd65efd15d4f1bbd57488035d4cca5ad8049d1b200ea5ea0f27f95d` | Euskadi (63); CPV propio; EV; 12 anuncios DOC_CN (versiones de anuncio) |

Página 2 (`extracto_PlataformasAgregadasSinMenores_20261024_030059.atom`; la original tiene 500 entradas):
| Tipo | Id | Bytes | SHA-256 del fragmento | Por qué está |
|---|---|---|---|---|
| entry | 16022422 | 11188 | `1d6790c8072de47c2e257cb1a9821aa33e38078660802febf6cd3483a1b489dc` | CPV propio; formalizado; varios DOC_FORM |
| entry | 20772644 | 5918 | `1bcfb1539652a43447eb7df2edb73442005337087886e27f382b7e80e8768dd1` | estado PRE (DOC_PIN); 3 lotes |
| entry | 8259141 | 118198 | `3c448385529fc74b829b3fc1c7525c109751cc9617be01c7f15a5e9f3bd20792` | Madrid (121); acuerdo marco con **110 `TenderResult`** (uno por adjudicatario), 86 ofertas, presupuesto `TaxExclusiveAmount=0` |
| entry | 20422617 | 9157 | `532f5e1d94f69e98317b33b298a0f2ade2ca884734ec8fe498a78d8e4ec5726d` | Cataluña; DESISTIMIENTO |
| entry | 20194183 | 8616 | `b62a6cdb4a14b5a7abfa79c5f948ffee6fb5262b82df8577d761dbd9d5143539` | Cataluña (ES513); CPV propio; desierto |
| entry | 20558535 | 7100 | `91a0360bd5e3f6680a606f6608f17cfdda2b80ec6cf273197a5a2458cd39d11d` | adjudicatario `schemeName="OTROS"` |

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
El repositorio es público: en `extracto_PlataformasAgregadasSinMenores_20261024_030059.atom` se han sustituido datos de personas físicas (1 adjudicataria persona física: NIF y nombre) por valores
ficticios con formato válido (DNI `99999001S`–`99999004H`, nombres «Persona Ficticia …»). El resto del archivo es
idéntico al descargado. SHA-256 del original descargado: `66fcf63248d82d4c0d830cab3be32f4645702d72571582151e203ae64cc0e826` (161848 bytes); el de la tabla es el del archivo seudonimizado.
