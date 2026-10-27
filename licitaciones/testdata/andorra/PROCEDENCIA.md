# Procedencia — Andorra (sin datos guardados)

**No se guarda ningún dato andorrano en el repositorio** porque el aviso legal del Govern d'Andorra
(https://www.govern.ad/avis-legal, leído el 26/10/2026) dice: «No es podran fer actes totals o parcials de reproducció,
publicació, **tractament informàtic**, distribució, difusió, transformació, compilació, modificació, distribució o
comunicació pública dels webs sense el consentiment previ i per escrit del Govern […] Queda absolutament prohibit l'ús
dels webs o de qualsevol dels seus elements **amb finalitats comercials**». Reutilizarlos requiere **autorización escrita
del Govern** (pendiente de decisión de Dirección/Legal). Aquí solo queda la evidencia de lo comprobado.

## Fuente oficial
- **Plataforma de Contractació del Sector Públic (PCSP) d'Andorra**: https://contractacio.govern.ad/SLE_Internet/ .
  Según el texto del Reglament de la Llei de contractació pública (Decret 38/2026, del 4-2-2026, arts. 49 y 50) que
  devolvió la búsqueda (copias en jurisprudencia.ad y legalize.dev, **no** el BOPA: POR VERIFICAR en el BOPA), es la
  plataforma oficial y los comuns publican en ella directamente o por interconexión. Software «SLE» de Altia (lo indican
  la página de error y las rutas `SLE_Internet`). Acceso a licitar con NIA y certificado andorrano.
- **BOPA** (Butlletí Oficial del Principat d'Andorra, https://www.bopa.ad/): publica los edictes de licitación y de
  adjudicación (secciones «Concursos i subhastes» y «Adjudicacions i ampliació de contractes»); ofrece alertas por correo.
  La web es una SPA cuyo API (`bopaazurefunctions.azurewebsites.net/api/...`, con claves de función en el JS) es **interno
  y no documentado**: no es un servicio de datos abiertos y no se ha usado.
- Andorra no está en la UE: no publica en TED; tampoco en PLACSP.
- No se ha encontrado portal de datos abiertos con contratación pública ni feed RSS/ATOM (búsqueda del 26/10/2026; POR
  VERIFICAR preguntando a SPCP@govern.ad, +376 872 272).

## Lo comprobado en la PCSP (26/10/2026)
| Recurso | URL | Resultado |
|---|---|---|
| Portada | https://contractacio.govern.ad/SLE_Internet/ | 200, HTML; menú público: Perfil del contractant, Registre de licitadors i empreses classificades, **Registre contractes**, Notificacions, Subscripció |
| Perfil del contractant | `/SLE_Internet/findTenders.doPublic?search=S` | 302 a `internetClosedSession.jsp` sin cookie de sesión; 200 con la cookie de la portada. Búsqueda HTML, sin exportación |
| Registre de contractes | `/SLE_Internet/findContracts.doPublic?search=S` y POST `findContracts.doPublic` | 200; botones de exportación Excel/PDF/«CSV» (`generadorInformes.doServlet?do=exportarConsultaContratos&docType=1/2/3`) |
| Exportación «CSV» (`docType=3`) tras una búsqueda vacía | `/SLE_Internet/generadorInformes.doServlet?do=exportarConsultaContratos&docType=3` | 200, `Content-Type: text/csv` pero el cuerpo es un **XLSX** (411 033 B, SHA-256 `aa3b92eaf27ec7b922b59de77b0beaf3ac07945c92a874d395c8a96b3393d0f5`), 2 516 filas = 2 de cabecera + **2 514 contratos** |
| robots.txt | https://contractacio.govern.ad/robots.txt | 404 |

### Columnas del XLSX del Registre de contractes (leídas con `zip_stream.py` + `safexml.py`)
`Núm. Expedient`, `Denominació`, `Entitat`, `Organisme`, `Tipus de contracte`, `Procediment`, y por cada lote un bloque
repetido de 20 columnas (20 bloques, columnas H a OQ): `Codi` (lote), `Objecte`, `Data adjudicació`, `Empresa adjudicatària`,
`Import adjudicació sense IGI`, `Import adjudicació amb IGI`, `Núm. contracte`, `Classe de contracte`,
`Data de formalització`, `Data d'inici del contracte`, `Data de fi del contracte`, `Data màxima de fi del contracte amb
possibles pròrrogues`, `Import compromès prorrogat`, `Data de formalització del contracte modificat`, `Data d'inici de la
modificació`, `Data de fi del contracte`, `Canvi de contractista…`, `Total compromès`, `Total liquidat`, `Motiu de la baixa`.

Observado: **sin NIF/NRT del adjudicatario** (solo nombre), sin CPV, sin NUTS, sin presupuesto base ni nº de ofertas;
IGI (impuesto andorrano) en lugar de IVA; incluye contratos menores («NEGOCIAT SENSE PUBLICITAT.CONTRACTE MENOR AMB
INVITACIÓ»); fechas de adjudicación imposibles (p. ej. `29/12/2034`); muchas columnas de fechas de contrato vacías en
las filas vistas. Procedimientos vistos: «OBERT [art. 43 LCP]», «ASSOCIACIÓ PER A LA INNOVACIÓ [ART. 47 LCP]»,
«NEGOCIAT SENSE PUBLICITAT.CONTRACTE MENOR AMB INVITACIÓ».

## Conclusión
Hay una fuente oficial con datos estructurados (exportación XLSX del Registre de contractes) y otra de anuncios (BOPA), pero
**ninguna con licencia de reutilización ni API/feed abierto**. Sin autorización escrita del Govern no se debe ingerir. Si se
autoriza: (1) adjudicaciones desde la exportación XLSX (sin NIF: la reconciliación de empresas sería solo por nombre, lo
que las NORMAS prohíben fusionar; habría que tratarlas como entidades separadas con baja confianza) y (2) licitaciones
abiertas desde el BOPA o el perfil del contractant (HTML).
