import test from "node:test";
import assert from "node:assert/strict";
import {
  antiguedadTexto, conAcceso, decidir, estadoEtiqueta, estadoMotor, filtrosAQuery, fechaTexto, importeTexto, limpiarCpv, limpiarNuts, mensajeDeError,
  nombreFuente, queryAFiltros, rutaPermitida, totalTexto, urlSegura,
} from "../lib/licitaciones.js";
import { viabilidadEtiqueta, admiteResumen, avisosDeAlertaTexto, canalEtiqueta, CANALES_ALERTA, ambitoTexto, eventoEtiqueta, filtroDeAlerta, filtroTexto, mensajeAlertas, sinLeerTexto } from "../lib/licitaciones.js";
import { SOBRES_OFERTA, autorSeccionTexto, estadoSeccionEtiqueta, mensajeOferta, pendientesOferta, precioAEnvio, resumenOfertaTexto, FILTROS_VACIOS, cercaniaTexto, costeErpTexto, mensajeParecidas, mensajeReglas, motivosTexto, reglasAEnvio, reglasAFormulario } from "../lib/licitaciones.js";
import { rutaNoExiste } from "../lib/licitaciones.js";
import {
  alturasTrimestres, competenciaDeCpv, fichaOrgHref, identificadoresTexto, orgAQuery, queryAOrg, repeticionTexto, trimestreTexto,
} from "../lib/licitaciones.js";
import {
  VENCEN_VACIO, agruparPorMes, confianzaFinTexto, prorrogasTexto, queryAVencen, vencenAQuery, vencenDeMercado, vencenProblema, venceEnTexto,
} from "../lib/licitaciones.js";
import {
  COMPETENCIA_VACIA, adjudicacionesDeCompetidor, bajaTexto, competenciaAQuery, competenciaAcotada, cuotaTexto, limpiarNifs, mercadoTexto, muestraPoca, muestraTexto,
  queryACompetencia, tendenciaEtiqueta,
} from "../lib/licitaciones.js";
import { accionEmbudo, avisoEstadoMotor, diasDePeriodo, ESTADOS_EMBUDO, etiquetaEmbudo, horasTexto, mensajeEmbudo, tasaExitoTexto } from "../lib/licitaciones.js";

const ID = "0b1f7a3e-1111-4222-8333-444444444444";

test("quién tiene acceso: grupos de licitaciones, dirección y servicio", () => {
  assert.ok(conAcceso({ grupos: ["licitaciones"] }));
  assert.ok(conAcceso({ grupos: ["comercial"] }));
  assert.ok(conAcceso({ roles: ["direccion"] }));
  assert.ok(conAcceso({ roles: ["servicio"] }));
  assert.ok(!conAcceso({ roles: ["usuario", "responsable"], grupos: ["finanzas"] }));
  assert.ok(!conAcceso({}));
  assert.ok(!conAcceso());
});

test("la pasarela solo deja pasar lecturas de tenders, ficha y estado", () => {
  assert.ok(rutaPermitida(["tenders"], "GET"));
  assert.ok(rutaPermitida(["tenders", ID], "GET"));
  assert.ok(rutaPermitida(["tenders", ID.toUpperCase()], "GET"));
  assert.ok(rutaPermitida(["ops", "status"], "GET"));
  for (const m of ["POST", "PATCH", "DELETE", "PUT"]) assert.ok(!rutaPermitida(["tenders"], m), m);
  for (const r of [["tenders", "no-es-uuid"], ["tenders", ID, "history"], ["tenders", "../ops/status"], ["alerts"], ["simulations"], ["ops"], ["ops", "detalle"], [], ["tenders", ""]]) {
    assert.ok(!rutaPermitida(r, "GET"), JSON.stringify(r));
  }
  assert.ok(!rutaPermitida("tenders", "GET"));
});

test("decidir: sin sesión 401, sin permiso 403, ruta no permitida 404, sin credencial 503", () => {
  const ok = { roles: [], grupos: ["licitaciones"] };
  assert.equal(decidir({ metodo: "GET", segmentos: ["tenders"], identidad: null, hayCredencial: true }).status, 401);
  assert.equal(decidir({ metodo: "GET", segmentos: ["tenders"], identidad: { roles: ["usuario"], grupos: ["finanzas"] }, hayCredencial: true }).status, 403);
  assert.equal(decidir({ metodo: "GET", segmentos: ["alerts"], identidad: ok, hayCredencial: true }).status, 404);
  assert.equal(decidir({ metodo: "POST", segmentos: ["tenders"], identidad: ok, hayCredencial: true }).status, 404);
  assert.equal(decidir({ metodo: "GET", segmentos: ["tenders"], identidad: ok, hayCredencial: false }).status, 503);
  assert.equal(decidir({ metodo: "GET", segmentos: ["tenders"], identidad: ok, hayCredencial: true }), null);
  // el permiso se comprueba antes que la ruta: quien no tiene acceso no averigua qué rutas existen
  assert.equal(decidir({ metodo: "GET", segmentos: ["nada"], identidad: { roles: [], grupos: [] }, hayCredencial: true }).status, 403);
});

test("importes con moneda e impuestos, y «—» si no son válidos", () => {
  assert.match(importeTexto({ valor: "100000.50", moneda: "EUR", impuestos: "sin_iva", significado: "valor_estimado" }), /^100\.000,50 € · sin IVA$/);
  assert.match(importeTexto({ valor: "900000", moneda: "EUR", impuestos: "con_iva", significado: "adjudicado" }, true), /^adjudicado · 900\.000,00 € · con IVA$/);
  assert.match(importeTexto({ valor: "10", moneda: "USD", impuestos: "desconocido" }), /USD · IVA no indicado/);
  for (const malo of [null, undefined, {}, { valor: "abc" }, { valor: "1e9" }, { valor: "<script>" }]) assert.equal(importeTexto(malo), "—");
});

test("las fechas inválidas no rompen la página", () => {
  assert.equal(fechaTexto(null), "—");
  assert.equal(fechaTexto("no es fecha"), "—");
  assert.match(fechaTexto("2026-10-27T10:00:00Z", false), /2026/);
});

test("solo se enlazan direcciones http y https", () => {
  assert.equal(urlSegura("https://contrataciondelestado.es/x?a=1"), "https://contrataciondelestado.es/x?a=1");
  for (const u of ["javascript:alert(1)", "data:text/html,x", "ftp://x", "//x", "no es url", "", null, undefined]) assert.equal(urlSegura(u), null, String(u));
});

test("limpieza de CPV y NUTS", () => {
  assert.deepEqual(limpiarCpv("72, 35125300;  72 abc 7"), ["72", "35125300"]);
  assert.deepEqual(limpiarCpv("123456789"), []);
  assert.deepEqual(limpiarNuts("es512  ES51 xx9999 1"), ["ES512", "ES51"]);
  assert.equal(limpiarCpv(Array.from({ length: 40 }, (_, i) => String(10 + i)).join(" ")).length, 20);
});

test("filtros → parámetros del motor", () => {
  const p = filtrosAQuery({
    q: "  videovigilancia ", cpv: "35125 72", nuts: "es512", estados: ["abierta", "rara"], importeMin: "1000,5", importeMax: "250000", orden: "relevancia", plazoHasta: "2026-12-01",
  });
  assert.equal(p.get("q"), "videovigilancia");
  assert.deepEqual(p.getAll("cpv"), ["35125", "72"]);
  assert.deepEqual(p.getAll("nuts"), ["ES512"]);
  assert.deepEqual(p.getAll("estado"), ["abierta"]);
  assert.equal(p.get("importe_min"), "1000.5");
  assert.equal(p.get("importe_max"), "250000");
  assert.equal(p.get("plazo_hasta"), "2026-12-01T23:59:59Z");
  assert.equal(p.get("orden"), "relevancia");
});

test("lo que no es válido se omite en lugar de provocar un 400", () => {
  const p = filtrosAQuery({ q: "a", cpv: "xx", importeMin: "mucho", importeMax: "-3", plazoHasta: "mañana", orden: "inventado", estados: [] });
  assert.equal(p.toString(), "");
  // la relevancia sin texto no existe: se omite
  assert.equal(filtrosAQuery({ q: "", orden: "relevancia" }).has("orden"), false);
  assert.equal(filtrosAQuery({ q: "", orden: "plazo" }).get("orden"), "plazo");
});

test("ida y vuelta entre los filtros y la dirección de la página", () => {
  const f = { q: "software", cpv: "72 35", nuts: "ES512", estados: ["abierta", "cerrada"], importeMin: "100", importeMax: "", orden: "importe", plazoHasta: "2026-12-01", modo: "" };
  const sp = new URLSearchParams(filtrosAQuery(f));
  assert.deepEqual(queryAFiltros(sp), f);
});

test("totales, antigüedad, estados y errores en castellano", () => {
  assert.equal(totalTexto({ valor: 1, relacion: "eq" }), "1 resultado");
  assert.equal(totalTexto({ valor: 42, relacion: "eq" }), "42 resultados");
  assert.match(totalTexto({ valor: 10000, relacion: "gte" }), /^al menos 10\.000 resultados$/);
  assert.equal(totalTexto(null), "");
  assert.equal(antiguedadTexto(30), "hace un momento");
  assert.equal(antiguedadTexto(1500), "hace 25 min");
  assert.equal(antiguedadTexto(10800), "hace 3 h");
  assert.equal(antiguedadTexto(200000), "hace 2 días");
  assert.equal(antiguedadTexto(null), "sin ingesta completa");
  assert.equal(estadoMotor("ok").clase, "ok");
  assert.equal(estadoMotor("caido").clase, "caido");
  assert.equal(estadoMotor("raro").clase, "aviso");
  assert.equal(estadoEtiqueta("abierta"), "Abierta");
  assert.equal(estadoEtiqueta("rara"), "rara");
  assert.equal(nombreFuente("placsp"), "PLACSP");
  assert.match(mensajeDeError(403), /acceso/);
  assert.match(mensajeDeError(502), /no está disponible/);
  assert.ok(!/10\.0|token|Bearer/i.test([401, 403, 400, 404, 429, 500].map(mensajeDeError).join(" ")));
});

import { diasTexto, encajeClase, fechaCivilTexto, mensajeResumen, ORIGEN_RESUMEN, totalesTexto, ventanaTexto } from "../lib/licitaciones.js";

test("encaje: clases por tramos y sin dato", () => {
  assert.equal(encajeClase(100), "alto");
  assert.equal(encajeClase(70), "alto");
  assert.equal(encajeClase(69), "medio");
  assert.equal(encajeClase(45), "medio");
  assert.equal(encajeClase(44), "bajo");
  assert.equal(encajeClase(0), "bajo");
  assert.equal(encajeClase(null), "sin");
  assert.equal(encajeClase(undefined), "sin");
});

test("plazos en días", () => {
  assert.equal(diasTexto(-1), "plazo terminado");
  assert.equal(diasTexto(0.4), "cierra hoy");
  assert.equal(diasTexto(1.2), "queda 1 día");
  assert.equal(diasTexto(12.9), "quedan 12 días");
  assert.equal(diasTexto(null), "");
});

test("la fecha del resumen es una fecha civil: no salta de día por la zona horaria", () => {
  assert.match(fechaCivilTexto("2026-10-28"), /28 de octubre de 2026/);
  assert.match(fechaCivilTexto("2026-01-01"), /1 de enero de 2026/);
  for (const malo of ["", null, "28/10/2026", "2026-13-45x", undefined]) assert.equal(fechaCivilTexto(malo), "—");
});

test("la ventana se muestra en hora de Madrid", () => {
  const t = ventanaTexto({ desde: "2026-10-27T15:00:00Z", hasta: "2026-10-28T15:00:00Z" });
  assert.match(t, /16:00/);
  assert.match(t, /→/);
  assert.equal(ventanaTexto(null), "");
  assert.equal(ventanaTexto({ desde: "no", hasta: "no" }), "");
});

test("cifras del resumen en una línea", () => {
  assert.equal(totalesTexto({ oportunidades: 1 }), "1 oportunidad");
  assert.equal(totalesTexto({ oportunidades: 12, adjudicaciones: 3, anuladas: 1 }), "12 oportunidades · 3 adjudicaciones · 1 anulada");
  assert.equal(totalesTexto({ oportunidades: 0, adjudicaciones: 0 }), "0 oportunidades");
  assert.equal(totalesTexto(null), "");
  assert.equal(ORIGEN_RESUMEN.programada, "de las 16:00");
});

test("mensajes del resumen en castellano y sin detalles internos", () => {
  assert.match(mensajeResumen(403), /Dirección/);
  assert.match(mensajeResumen(404), /16:00/);
  assert.match(mensajeResumen(500), /No se ha podido/);
  assert.ok(!/token|Bearer|10\.0/i.test([401, 403, 404, 500].map(mensajeResumen).join(" ")));
});

test("el embudo: etiquetas, acciones y periodos", () => {
  assert.deepEqual(ESTADOS_EMBUDO.map(([k]) => k), ["detectada", "en_estudio", "presentada", "ganada", "perdida", "descartada"]);
  assert.equal(etiquetaEmbudo("en_estudio"), "En estudio");
  assert.equal(etiquetaEmbudo("raro"), "raro");
  assert.equal(accionEmbudo("detectada", "en_estudio"), "Pasar a estudio");
  assert.equal(accionEmbudo("descartada", "en_estudio"), "Reabrir (en estudio)");
  assert.match(accionEmbudo("presentada", "perdida"), /perdida/);
  assert.equal(diasDePeriodo("hoy"), 1);
  assert.equal(diasDePeriodo("7d"), 7);
  assert.equal(diasDePeriodo("90d"), 90);
  assert.equal(diasDePeriodo("lo que sea"), 30);       // por defecto, 30 días
});

test("la tasa de éxito no se enseña como cifra si hay pocas decididas", () => {
  assert.equal(tasaExitoTexto({ valor: 0.4, ganadas: 2, decididas: 5, minimo: 5 }), "40 % (2 de 5)");
  assert.equal(tasaExitoTexto({ valor: 0, ganadas: 0, decididas: 8, minimo: 5 }), "0 % (0 de 8)");
  assert.match(tasaExitoTexto({ valor: null, ganadas: 1, decididas: 3, minimo: 5 }), /Aún sin datos suficientes \(3 de 5 decididas\)/);
  assert.equal(tasaExitoTexto(null), "—");
});

test("horas hasta decidir: horas hasta dos días y días a partir de ahí", () => {
  assert.equal(horasTexto(3), "3 h");
  assert.equal(horasTexto(25.5), "25,5 h");
  assert.equal(horasTexto(72), "3 días");
  assert.equal(horasTexto(null), "—");
  assert.equal(horasTexto(undefined), "—");
});

test("mensajes del embudo en castellano y sin detalles internos", () => {
  assert.match(mensajeEmbudo(403), /Dirección/);
  assert.match(mensajeEmbudo(422), /no está permitido/);
  assert.match(mensajeEmbudo(503), /motor/);
  assert.ok(!/token|Bearer|10\.0|psycopg|Traceback/i.test([401, 403, 404, 422, 503, 500].map(mensajeEmbudo).join(" ")));
});

test("aviso cuando el expediente ya no está abierto en el motor", () => {
  assert.equal(avisoEstadoMotor("abierta"), null);
  assert.equal(avisoEstadoMotor("anuncio_previo"), null);
  assert.equal(avisoEstadoMotor(null), null);
  assert.equal(avisoEstadoMotor(undefined), null);
  assert.equal(avisoEstadoMotor("anulada"), "En el motor: Anulada");
  assert.equal(avisoEstadoMotor("adjudicada"), "En el motor: Adjudicada");
});

test("del buscador a una alerta: solo lo válido y siempre listas", () => {
  assert.deepEqual(filtroDeAlerta({ q: " cámaras ", cpv: "32323500 72 xx 72", nuts: "es512", estados: ["abierta", "rara"], importeMin: "1000", importeMax: "2,5" }),
    { q: "cámaras", cpv: ["32323500", "72"], nuts: ["ES512"], estado: ["abierta"], importe_min: "1000", importe_max: "2.5" });
  assert.deepEqual(filtroDeAlerta({ q: "a", cpv: "", nuts: "", estados: [], importeMin: "mucho" }), {});        // sin criterios válidos: no hay alerta posible
  assert.deepEqual(filtroDeAlerta({}), {});
});

test("la frase de una alerta cuenta lo que busca", () => {
  assert.equal(filtroTexto({ q: "cámaras", cpv: ["32323500"], nuts: ["ES512"], estado: ["abierta"], importe_min: "100000" }),
    "texto «cámaras» · CPV 32323500 · zona ES512 · estado abierta · desde 100.000 €");
  assert.equal(filtroTexto({ procedimiento: ["abierto_simplificado"], comprador: ["nif:P1708500E"] }), "comprador nif:P1708500E · procedimiento abierto simplificado");
  assert.equal(filtroTexto(null), "");
  assert.equal(filtroTexto({}), "");
});

test("etiquetas, ámbito y avisos sin leer", () => {
  assert.equal(eventoEtiqueta("licitacion.nueva"), "Nueva licitación");
  assert.equal(eventoEtiqueta("licitacion.rara"), "rara");
  assert.equal(ambitoTexto({ ambito: "personal" }), "Personal");
  assert.equal(ambitoTexto({ ambito: "departamento", departamento: "licitaciones" }), "Departamento licitaciones");
  assert.equal(sinLeerTexto(0), "Sin avisos nuevos");
  assert.equal(sinLeerTexto(1), "1 aviso sin leer");
  assert.equal(sinLeerTexto(7), "7 avisos sin leer");
});

test("mensajes de las alertas en castellano y sin detalles internos", () => {
  assert.match(mensajeAlertas(403), /responsable o Dirección/);
  assert.match(mensajeAlertas(422), /al menos un criterio/);
  assert.match(mensajeAlertas(404), /ya no existe/);
  assert.ok(!/token|Bearer|psycopg|Traceback/i.test([401, 403, 404, 422, 500].map(mensajeAlertas).join(" ")));
});

test("las alertas en el resumen: solo las de departamento, y las cifras lo cuentan", () => {
  assert.equal(admiteResumen({ ambito: "departamento" }), true);
  assert.equal(admiteResumen({ ambito: "personal" }), false);
  assert.equal(admiteResumen(null), false);
  assert.deepEqual(CANALES_ALERTA.map(([k]) => k), ["panel", "resumen_diario", "correo"]);
  assert.equal(canalEtiqueta("resumen_diario"), "En el panel y en el resumen de las 16:00");
  assert.equal(canalEtiqueta("panel"), "Solo en el panel");
  assert.equal(totalesTexto({ oportunidades: 2, alertas: 1 }), "2 oportunidades · 1 aviso de alertas");
  assert.equal(totalesTexto({ oportunidades: 2, alertas: 6 }), "2 oportunidades · 6 avisos de alertas");
  assert.equal(totalesTexto({ oportunidades: 2, alertas: 0 }), "2 oportunidades");
  assert.equal(avisosDeAlertaTexto({ total: 1, avisos: [{}] }), "1 aviso");
  assert.equal(avisosDeAlertaTexto({ total: 7, avisos: [{}, {}, {}] }), "7 avisos (se detallan 3)");
  assert.equal(avisosDeAlertaTexto(null), "");
});

test("el informe de Viabilidad: una etiqueta clara y nunca una decisión", () => {
  assert.deepEqual(viabilidadEtiqueta({ recomendacion: "ir" }), { texto: "Viabilidad: IR", clase: "abierta" });
  assert.deepEqual(viabilidadEtiqueta({ recomendacion: "no_ir" }), { texto: "Viabilidad: NO IR", clase: "anulada" });
  assert.equal(viabilidadEtiqueta({ recomendacion: "revisar" }).texto, "Viabilidad: REVISAR");
  assert.equal(viabilidadEtiqueta({ recomendacion: "sin_recomendacion" }).texto, "Viabilidad: Sin recomendación");
  assert.equal(viabilidadEtiqueta({ recomendacion: "lo que sea" }).texto, "Viabilidad: Sin recomendación");   // un valor raro no rompe la pantalla
  for (const nada of [null, undefined, "", 5]) assert.equal(viabilidadEtiqueta(nada), null);                    // sin informe, sin etiqueta
});


test("la pasarela deja pasar la lista de adjudicaciones y de competidores, y nada más de ellas", () => {
  assert.ok(rutaPermitida(["awards"], "GET"));
  assert.ok(rutaPermitida(["competitors"], "GET"));
  for (const r of [["awards", ID], ["competitors", "x"], ["awards", "export"], ["organizations"], ["alerts"]]) assert.ok(!rutaPermitida(r, "GET"), JSON.stringify(r));
  assert.ok(!rutaPermitida(["awards"], "POST"));
});

test("competencia: el mercado hay que acotarlo con CPV, zona o comprador", () => {
  assert.ok(!competenciaAcotada(COMPETENCIA_VACIA));
  assert.ok(!competenciaAcotada({ ...COMPETENCIA_VACIA, desde: "2025-01-01", cpv: "abc" }));
  assert.ok(competenciaAcotada({ ...COMPETENCIA_VACIA, cpv: "72" }));
  assert.ok(competenciaAcotada({ ...COMPETENCIA_VACIA, nuts: "es512" }));
  assert.ok(competenciaAcotada({ ...COMPETENCIA_VACIA, comprador: "p1708500e" }));
  assert.ok(!competenciaAcotada({ ...COMPETENCIA_VACIA, comprador: "corto" }));
});

test("competencia: filtros del formulario a parámetros del motor y de vuelta", () => {
  assert.deepEqual(limpiarNifs("p1708500e, nif:B12345678 x B12345678 corto"), ["nif:P1708500E", "nif:B12345678"]);
  const f = { cpv: "72 35125 mal", nuts: "es512", comprador: "p1708500e", desde: "2025-01-01", hasta: "2026-10-27", orden: "contratos" };
  const q = competenciaAQuery(f);
  assert.deepEqual([q.getAll("cpv"), q.getAll("nuts"), q.getAll("comprador"), q.get("desde"), q.get("hasta"), q.get("orden")],
    [["72", "35125"], ["ES512"], ["nif:P1708500E"], "2025-01-01", "2026-10-27", "contratos"]);
  assert.deepEqual(queryACompetencia(q), { cpv: "72 35125", nuts: "ES512", comprador: "P1708500E", desde: "2025-01-01", hasta: "2026-10-27", orden: "contratos" });
  // lo que no es válido se omite en vez de mandar un 400: fechas imposibles, desde posterior a hasta, orden desconocido
  const m = competenciaAQuery({ cpv: "72", desde: "2026-13-45", hasta: "ayer", orden: "plazo" });
  assert.equal(m.toString(), "cpv=72");
  assert.equal(competenciaAQuery({ cpv: "72", desde: "2026-05-01", hasta: "2026-01-01" }).has("hasta"), false);
  assert.equal(competenciaAQuery({ cpv: "72", orden: "cuota" }).has("orden"), false);
  assert.equal(competenciaAQuery({ cpv: "72", desde: "2027-02-30" }).has("desde"), false);            // una fecha que no existe no se manda
});

test("competencia: las adjudicaciones de una empresa usan los mismos filtros del mercado", () => {
  const p = adjudicacionesDeCompetidor({ ...COMPETENCIA_VACIA, cpv: "72", desde: "2025-01-01", orden: "contratos" }, "uuid-1");
  assert.deepEqual([p.get("cpv"), p.get("adjudicada_desde"), p.get("adjudicatario"), p.get("resultado"), p.get("orden"), p.get("limit")], ["72", "2025-01-01", "uuid-1", "adjudicado", "fecha", "5"]);
  assert.ok(!p.has("desde") && !p.has("hasta"));
});

test("competencia: cuota, baja, tendencia y muestra se muestran con sus límites", () => {
  assert.equal(cuotaTexto(0.66667), "66,7 %");
  assert.equal(cuotaTexto(1), "100,0 %");
  assert.equal(cuotaTexto(0.0004), "<0,1 %");
  assert.equal(cuotaTexto(0), "0,0 %");
  for (const malo of [null, undefined, -0.1, 1.5, NaN, "0.5"]) assert.equal(cuotaTexto(malo), "—", String(malo));
  assert.equal(bajaTexto(0.2), "20,0 %");
  for (const malo of [null, undefined, -0.5, 1.2, "x"]) assert.equal(bajaTexto(malo), "—", String(malo));
  assert.equal(tendenciaEtiqueta("sube").texto, "Sube");
  assert.equal(tendenciaEtiqueta("raro").texto, "Sin datos");
  assert.equal(muestraTexto({ adjudicaciones: 6, desde: "2025-02-01", hasta: "2026-09-01" }), "6 adjudicaciones entre febrero de 2025 y septiembre de 2026");
  assert.equal(muestraTexto({ adjudicaciones: 1 }), "1 adjudicación");
  assert.match(muestraTexto({ adjudicaciones: 0 }), /No hay adjudicaciones/);
  assert.ok(muestraPoca({ adjudicaciones: 9 }) && !muestraPoca({ adjudicaciones: 10 }) && !muestraPoca({ adjudicaciones: 0 }) && !muestraPoca(null));
  assert.equal(mercadoTexto({ cpv: "72", nuts: "es512", comprador: "p1708500e", desde: "2025-01-01", hasta: "" }), "CPV 72 · zona ES512 · comprador P1708500E · desde 2025-01-01");
});


test("la pasarela deja pasar la lista de contratos que vencen y nada más de ella", () => {
  assert.ok(rutaPermitida(["expiring-contracts"], "GET"));
  assert.ok(!rutaPermitida(["expiring-contracts", ID], "GET"));
  assert.ok(!rutaPermitida(["expiring-contracts"], "POST"));
});

test("contratos que vencen: filtros del formulario a parámetros del motor y de vuelta", () => {
  const f = { cpv: "72 mal", nuts: "es512", comprador: "p1708500e", importeMin: "50000,50", desde: "2027-01-01", hasta: "2027-12-31", conProrrogas: true };
  const q = vencenAQuery(f);
  assert.deepEqual([q.getAll("cpv"), q.getAll("nuts"), q.getAll("comprador"), q.get("importe_min"), q.get("vence_desde"), q.get("vence_hasta"), q.get("con_prorrogas")],
    [["72"], ["ES512"], ["nif:P1708500E"], "50000.50", "2027-01-01", "2027-12-31", "true"]);
  assert.deepEqual(queryAVencen(q), { cpv: "72", nuts: "ES512", comprador: "P1708500E", importeMin: "50000.50", desde: "2027-01-01", hasta: "2027-12-31", conProrrogas: true });
  assert.equal(vencenAQuery(VENCEN_VACIO).toString(), "");                       // sin nada: el motor usa sus fechas por defecto
  assert.equal(vencenAQuery({ ...VENCEN_VACIO, desde: "2027-02-30", importeMin: "abc" }).toString(), "");
});

test("contratos que vencen: el periodo se valida antes de preguntar al motor", () => {
  assert.equal(vencenProblema(VENCEN_VACIO), null);
  assert.equal(vencenProblema({ desde: "2027-01-01", hasta: "2027-12-31" }), null);
  assert.equal(vencenProblema({ desde: "2027-01-01", hasta: "2030-01-01" }), null);              // 36 meses justos
  assert.match(vencenProblema({ desde: "2027-01-01", hasta: "2030-01-02" }), /36 meses/);
  assert.match(vencenProblema({ desde: "2027-05-01", hasta: "2027-01-01" }), /posterior/);
  assert.equal(vencenProblema({ desde: "2027-01-01" }), null);
});

test("contratos que vencen: agrupación por mes, plazos y fiabilidad", () => {
  const g = agruparPorMes([{ fecha_fin: "2027-02-10" }, { fecha_fin: "2027-02-28" }, { fecha_fin: "2027-05-31" }, { fecha_fin: null }]);
  assert.deepEqual(g.map((x) => [x.mes, x.titulo, x.items.length]), [["2027-02", "febrero de 2027", 2], ["2027-05", "mayo de 2027", 1], ["sin-fecha", "Sin fecha", 1]]);
  assert.deepEqual(agruparPorMes(null), []);
  const hoy = "2026-10-28";
  assert.equal(venceEnTexto("2026-10-01", hoy), "ya ha terminado");
  assert.equal(venceEnTexto("2026-10-28", hoy), "termina hoy");
  assert.equal(venceEnTexto("2026-10-29", hoy), "termina mañana");
  assert.equal(venceEnTexto("2026-11-20", hoy), "en 23 días");
  assert.equal(venceEnTexto("2027-02-28", hoy), "en 4 meses");
  assert.equal(venceEnTexto("2030-02-28", hoy), "en 3 años");
  assert.equal(venceEnTexto("mal", hoy), "");
  assert.match(confianzaFinTexto(0.9), /fiable/);
  assert.match(confianzaFinTexto(0.7), /formalización/);
  assert.match(confianzaFinTexto(0.4), /orientativa/);
  assert.equal(confianzaFinTexto(null), "fecha estimada");
});

test("contratos que vencen: qué se dice de las prórrogas sin inventar", () => {
  const f = (x) => `«${x}»`;
  assert.equal(prorrogasTexto({ prorrogas_posibles: false }, f), "Sin prórrogas previstas");
  assert.equal(prorrogasTexto({ prorrogas_posibles: true, fecha_fin_con_prorrogas: "2029-02-28" }, f), "Con prórrogas podría llegar hasta el «2029-02-28»");
  assert.match(prorrogasTexto({ prorrogas_posibles: true, fecha_fin_con_prorrogas: null }, f), /sin fecha calculada/);
  assert.match(prorrogasTexto({ prorrogas_posibles: null, prorrogas_texto: "Consultar el pliego" }, f), /pliego/);
  assert.equal(prorrogasTexto({ prorrogas_posibles: null, prorrogas_texto: null }, f), "Prórrogas: no consta");
});

test("contratos que vencen: enlace desde competencia con el mismo mercado", () => {
  assert.equal(vencenDeMercado({ cpv: "72 35125", nuts: "es512", comprador: "" }), "/licitaciones/vencen?cpv=72&cpv=35125&nuts=ES512");
  assert.equal(vencenDeMercado({ cpv: "", nuts: "", comprador: "" }), "/licitaciones/vencen");
});


test("la pasarela deja pasar la ficha de una organización solo por UUID", () => {
  assert.ok(rutaPermitida(["organizations", ID], "GET"));
  assert.ok(rutaPermitida(["organizations", ID.toUpperCase()], "GET"));
  for (const r of [["organizations"], ["organizations", "nif:B11111111"], ["organizations", "Uno Sistemas SL"], ["organizations", ID, "x"], ["organizations", ""], ["organizations", "../ops/status"]]) {
    assert.ok(!rutaPermitida(r, "GET"), JSON.stringify(r));
  }
  assert.ok(!rutaPermitida(["organizations", ID], "POST"));
});

test("ficha de organización: enlaces, filtros y textos", () => {
  assert.equal(fichaOrgHref(ID), `/licitaciones/organizaciones/${ID}`);
  for (const malo of [null, undefined, "", "nif:B11111111", "no-es-uuid", `${ID}/x`]) assert.equal(fichaOrgHref(malo), null, String(malo));
  const q = orgAQuery({ desde: "2025-01-01", hasta: "2026-12-31", cpv: "72 mal 35125" });
  assert.deepEqual([q.get("desde"), q.get("hasta"), q.getAll("cpv")], ["2025-01-01", "2026-12-31", ["72", "35125"]]);
  assert.deepEqual(queryAOrg(q), { desde: "2025-01-01", hasta: "2026-12-31", cpv: "72 35125" });
  assert.equal(orgAQuery({ desde: "2026-02-30", hasta: "ayer", cpv: "" }).toString(), "");
  assert.equal(orgAQuery({ desde: "2026-05-01", hasta: "2026-01-01", cpv: "" }).has("hasta"), false);
  assert.equal(identificadoresTexto([{ esquema: "NIF", valor: "Q0818001J" }, { esquema: "DIR3", valor: "L01082000" }]), "NIF Q0818001J · DIR3 L01082000");
  assert.equal(identificadoresTexto(null), "");
  assert.equal(trimestreTexto("2026-T3"), "T3 2026");
  assert.equal(trimestreTexto("raro"), "raro");
  assert.equal(trimestreTexto(null), "—");
  assert.match(repeticionTexto(0.6), /^60 % .*muy concentrado/);
  assert.match(repeticionTexto(0.25), /^25 % .*más frecuente/);
  for (const malo of [null, undefined, -1, 1.5, NaN, "0.5"]) assert.equal(repeticionTexto(malo), "", String(malo));
  assert.deepEqual(alturasTrimestres([{ contratos: 10 }, { contratos: 5 }, { contratos: 1 }, { contratos: 0 }]), [100, 50, 10, 0]);
  assert.deepEqual(alturasTrimestres([{ contratos: 1000 }, { contratos: 1 }]), [100, 6]);          // un trimestre con contratos siempre se ve
  assert.deepEqual(alturasTrimestres(null), []);
  assert.equal(competenciaDeCpv("35125"), "/licitaciones/competencia?cpv=35125");
  assert.equal(competenciaDeCpv("<script>"), "/licitaciones/competencia");
});


test("un 404 de «la ruta no existe» (motor desactualizado) no se confunde con «ese dato no existe»", () => {
  assert.ok(rutaNoExiste({ status: 404, detalle: "La ruta no existe." }));
  assert.ok(rutaNoExiste({ status: 404, detalle: "La ruta no existe" }));
  assert.ok(!rutaNoExiste({ status: 404, detalle: "No hay datos de esa organización." }));
  assert.ok(!rutaNoExiste({ status: 404, detalle: "El expediente no existe." }));
  assert.ok(!rutaNoExiste({ status: 404 }));
  assert.ok(!rutaNoExiste({ status: 500, detalle: "La ruta no existe." }));
  assert.ok(!rutaNoExiste(null));
  assert.match(mensajeDeError(404, "La ruta no existe."), /todavía no tiene esta función.*actualizarlo/);
  assert.equal(mensajeDeError(404, "No hay datos de esa organización."), "No se ha encontrado.");
  assert.equal(mensajeDeError(404), "No se ha encontrado.");
  assert.match(mensajeDeError(401, "x"), /sesión/);
  assert.match(mensajeDeError(503, "El motor de licitaciones no está disponible"), /no está disponible/);
});

// ---- Petición del informe de viabilidad (botón del embudo) ----
import { hayPeticionEnCurso, peticionViabilidad, puedePedirViabilidad, textoPedirViabilidad } from "../lib/licitaciones.js";

test("peticionViabilidad: en curso si es reciente, error con su texto, y una vieja se da por perdida", () => {
  const ahora = Date.parse("2026-10-28T10:30:00Z");
  assert.equal(peticionViabilidad({}, ahora), null);
  assert.equal(peticionViabilidad({ viabilidad_peticion: null }, ahora), null);
  assert.deepEqual(peticionViabilidad({ viabilidad_peticion: { estado: "en_curso", en: "2026-10-28T10:20:00Z" } }, ahora), { estado: "en_curso" });
  assert.equal(peticionViabilidad({ viabilidad_peticion: { estado: "en_curso", en: "2026-10-28T10:00:00Z" } }, ahora), null);   // 30 min: perdida
  assert.equal(peticionViabilidad({ viabilidad_peticion: { estado: "en_curso", en: "basura" } }, ahora), null);
  assert.deepEqual(peticionViabilidad({ viabilidad_peticion: { estado: "error", error: "El modelo no está disponible" } }, ahora), { estado: "error", error: "El modelo no está disponible" });
  assert.equal(peticionViabilidad({ viabilidad_peticion: { estado: "error" } }, ahora).error, "No se ha podido generar el informe.");
});

test("puedePedirViabilidad: solo viva, vinculada al motor y sin otra petición en curso", () => {
  const ahora = Date.parse("2026-10-28T10:30:00Z");
  const base = { motor_id: "u", estado: "detectada" };
  assert.equal(puedePedirViabilidad(base, ahora), true);
  assert.equal(puedePedirViabilidad({ ...base, estado: "en_estudio" }, ahora), true);
  assert.equal(puedePedirViabilidad({ ...base, motor_id: null }, ahora), false);
  for (const estado of ["ganada", "perdida", "descartada"]) assert.equal(puedePedirViabilidad({ ...base, estado }, ahora), false, estado);
  assert.equal(puedePedirViabilidad({ ...base, viabilidad_peticion: { estado: "en_curso", en: "2026-10-28T10:25:00Z" } }, ahora), false);
  assert.equal(puedePedirViabilidad({ ...base, viabilidad_peticion: { estado: "error", error: "x" } }, ahora), true);        // tras un error se puede reintentar
});

test("textoPedirViabilidad y hayPeticionEnCurso", () => {
  assert.equal(textoPedirViabilidad({}), "Pedir informe de viabilidad");
  assert.equal(textoPedirViabilidad({ viabilidad: { recomendacion: "ir" } }), "Volver a pedir el informe de viabilidad");
  const ahora = Date.parse("2026-10-28T10:30:00Z");
  assert.equal(hayPeticionEnCurso([{}, { viabilidad_peticion: { estado: "en_curso", en: "2026-10-28T10:29:00Z" } }], ahora), true);
  assert.equal(hayPeticionEnCurso([{}, { viabilidad_peticion: { estado: "error", error: "x" } }], ahora), false);
  assert.equal(hayPeticionEnCurso(undefined, ahora), false);
});

// ---- Canal «correo» de las alertas ----
import { canalDeAlertaTexto, canalesDe, correoValido } from "../lib/licitaciones.js";

test("canalesDe: el resumen solo para departamentos; el correo para todos", () => {
  assert.deepEqual(canalesDe("personal").map(([k]) => k), ["panel", "correo"]);
  assert.deepEqual(canalesDe("departamento").map(([k]) => k), ["panel", "resumen_diario", "correo"]);
});

test("correoValido: solo direcciones @101.cat", () => {
  for (const ok of ["albert@101.cat", " Marta.Puig+x@101.CAT "]) assert.equal(correoValido(ok), true, ok);
  for (const mal of ["", null, "x@gmail.com", "x@101.cat.evil.com", "x@sub.101.cat", "x@evil101.cat", "a b@101.cat", "a@101.cat,b@gmail.com", "x@101.cat\nBcc: y@z.com"]) assert.equal(correoValido(mal), false, String(mal));
});

test("canalDeAlertaTexto: dónde avisa una alerta", () => {
  assert.equal(canalDeAlertaTexto({ canal: "correo", correo_destino: "a@101.cat" }), "Por correo a a@101.cat");
  assert.equal(canalDeAlertaTexto({ canal: "resumen_diario" }), "En el panel y en el resumen de las 16:00");
  assert.equal(canalDeAlertaTexto({ canal: "panel" }), "");
});

// ---- Alertas de competencia ----
import { competenciaGuardable, competidoresDeTexto, esCompetencia, ganadoresTexto, TIPOS_ALERTA, vigilaTexto } from "../lib/licitaciones.js";

test("competidoresDeTexto: NIF de la lista, sin repetidos y sin lo que no lo es", () => {
  assert.deepEqual(competidoresDeTexto("b12345678, A08000143\nnif:b12345678 Seguridad corto"), ["B12345678", "A08000143"]);
  assert.deepEqual(competidoresDeTexto(""), []);
  assert.deepEqual(competidoresDeTexto(null), []);
  assert.equal(competidoresDeTexto(Array.from({ length: 30 }, (_, i) => `A${String(i).padStart(8, "0")}`).join(" ")).length, 20);
});

test("competenciaGuardable: competidores concretos o algún criterio de mercado", () => {
  assert.equal(competenciaGuardable({ competidores: "B12345678" }), true);
  assert.equal(competenciaGuardable({ competidores: "", cpv: "32323500" }), true);
  assert.equal(competenciaGuardable({ competidores: "", comprador: "P1708500E" }), true);
  assert.equal(competenciaGuardable({ competidores: "Seguridad SL", cpv: "" }), false);
  assert.equal(competenciaGuardable({ competidores: "" }), false);
});

test("filtroDeAlerta lleva el comprador como nif:", () => {
  assert.deepEqual(filtroDeAlerta({ comprador: "p1708500e" }), { comprador: ["nif:P1708500E"] });
});

test("textos de una alerta de competencia y de su aviso", () => {
  assert.equal(esCompetencia({ tipo: "competencia" }), true);
  assert.equal(esCompetencia({ tipo: "licitacion" }), false);
  assert.deepEqual(TIPOS_ALERTA.map(([k]) => k), ["licitacion", "competencia"]);
  assert.equal(vigilaTexto({ competidores: ["B12345678", "A08000143"] }), "B12345678, A08000143");
  assert.equal(vigilaTexto({ competidores: [] }), "cualquier adjudicatario");
  assert.equal(eventoEtiqueta("competencia.adjudicada"), "Competencia: adjudicada");
  assert.deepEqual(ganadoresTexto({ ganadores: [{ nombre: "Seguridad SL", nif: "B12345678", importe: "90000.00", lote: "2" }, { nombre: "Pedro Pérez", nif: null, importe: null, lote: "1" }] }),
    ["Ganó Seguridad SL · B12345678 · 90.000 € sin IVA · lote 2", "Ganó Pedro Pérez"]);
  assert.deepEqual(ganadoresTexto(null), []);
});

// ---- Cuadro «qué ha hecho la gente con Viabilidad» ----
import { viabilidadFilas, viabilidadPocosDatos } from "../lib/licitaciones.js";

const VIAB = { informes: 14, minimo: 5, por_recomendacion: {
  ir: { informes: 6, seguidos: 3, contrarios: 1, pendientes: 2, ganadas: 1, perdidas: 1 },
  no_ir: { informes: 1, seguidos: 1, contrarios: 0, pendientes: 0, ganadas: 0, perdidas: 0 },
  revisar: { informes: 0, seguidos: 0, contrarios: 0, pendientes: 0, ganadas: 0, perdidas: 0 } } };

test("viabilidadFilas: una fila por recomendación con informes, con singular y plural", () => {
  assert.deepEqual(viabilidadFilas(VIAB), [
    { clave: "ir", titulo: "Recomendó IR", informes: 6, seguimiento: "3 seguidas · 1 en contra · 2 pendientes", resultado: "1 ganada · 1 perdida" },
    { clave: "no_ir", titulo: "Recomendó NO IR", informes: 1, seguimiento: "1 seguida · 0 en contra", resultado: "—" },
  ]);
  assert.deepEqual(viabilidadFilas(null), []);
  assert.deepEqual(viabilidadFilas({ por_recomendacion: { ir: { informes: 0 } } }), []);
});

test("viabilidadFilas: «revisar» no tiene seguimiento, solo pendientes y resultado", () => {
  const f = viabilidadFilas({ por_recomendacion: { revisar: { informes: 3, seguidos: 0, contrarios: 0, pendientes: 1, ganadas: 2, perdidas: 0 } } });
  assert.deepEqual(f, [{ clave: "revisar", titulo: "Pidió REVISAR", informes: 3, seguimiento: "1 pendiente", resultado: "2 ganadas · 0 perdidas" }]);
});

test("viabilidadPocosDatos: con menos resueltas que el mínimo no se concluye nada", () => {
  assert.equal(viabilidadPocosDatos(VIAB), true);                                                  // 2 resueltas de 5
  assert.equal(viabilidadPocosDatos({ minimo: 5, por_recomendacion: { ir: { ganadas: 3, perdidas: 2 } } }), false);
  assert.equal(viabilidadPocosDatos(null), true);
});

// ---- Plazo en el calendario ----
import { calendarioEstado, mensajeCalendario, puedeAnadirAlCalendario, textoAnadirCalendario, textoEnCalendario } from "../lib/licitaciones.js";

test("calendarioEstado: no está, está al día o el plazo ha cambiado", () => {
  assert.equal(calendarioEstado({ fecha_limite: "2026-11-20T09:00:00+00:00" }), "no");
  assert.equal(calendarioEstado({ calendario_plazo: "2026-11-20T09:00:00+00:00", fecha_limite: "2026-11-20T10:00:00+01:00" }), "ok");        // la misma hora en otra zona
  assert.equal(calendarioEstado({ calendario_plazo: "2026-11-20T09:00:00+00:00", fecha_limite: "2026-11-25T09:00:00+00:00" }), "desfasado");
  assert.equal(calendarioEstado({ calendario_plazo: "2026-11-20T09:00:00+00:00", fecha_limite: null }), "desfasado");
  assert.equal(calendarioEstado(null), "no");
});

test("puedeAnadirAlCalendario: viva, vinculada y con plazo futuro", () => {
  const ahora = Date.parse("2026-10-28T12:00:00Z");
  const base = { motor_id: "u", estado: "en_estudio", fecha_limite: "2026-11-20T09:00:00+00:00" };
  assert.equal(puedeAnadirAlCalendario(base, ahora), true);
  assert.equal(puedeAnadirAlCalendario({ ...base, motor_id: null }, ahora), false);
  assert.equal(puedeAnadirAlCalendario({ ...base, fecha_limite: "2026-10-01T09:00:00+00:00" }, ahora), false);
  assert.equal(puedeAnadirAlCalendario({ ...base, fecha_limite: null }, ahora), false);
  for (const estado of ["ganada", "perdida", "descartada"]) assert.equal(puedeAnadirAlCalendario({ ...base, estado }, ahora), false, estado);
});

test("textos del plazo en el calendario", () => {
  const ok = { calendario_plazo: "2026-11-20T09:00:00+00:00", fecha_limite: "2026-11-20T09:00:00+00:00" };
  const viejo = { calendario_plazo: "2026-11-20T09:00:00+00:00", fecha_limite: "2026-11-25T09:00:00+00:00" };
  assert.equal(textoAnadirCalendario({}), "Añadir el plazo al calendario");
  assert.equal(textoAnadirCalendario(viejo), "Actualizar el plazo en el calendario");
  assert.equal(textoEnCalendario(ok), "Plazo en el calendario");
  assert.match(textoEnCalendario(viejo), /desfasado/);
  assert.equal(textoEnCalendario({}), "");
  assert.match(mensajeCalendario(503), /calendario/);
  assert.match(mensajeCalendario(422), /ya está resuelta o su plazo ha pasado/);
  assert.match(mensajeCalendario(403), /Dirección/);
});

// ---- Pliegos: documentos, antivirus y requisitos con cita ----
import { estadoPliego, estadoRequisito, lecturaPliego, lugarCita, mensajePliegos, puedeDescargarPliego, resumenRequisitos, tipoRequisito } from "../lib/licitaciones.js";

test("estadoPliego: lo que se dice de cada documento", () => {
  assert.deepEqual(estadoPliego(null), { texto: "Sin descargar", clase: "" });
  assert.equal(estadoPliego({ estado: "limpio" }).clase, "abierta");
  assert.equal(estadoPliego({ estado: "infectado" }).clase, "anulada");
  assert.match(estadoPliego({ estado: "no_analizable" }).texto, /No analizable/);
  assert.match(estadoPliego({ estado: "con_macros" }).texto, /solo se lee el texto/);
});

test("puedeDescargarPliego: bajar o reintentar, nunca con un infectado ni uno ya leído", () => {
  assert.equal(puedeDescargarPliego(null), true);
  assert.equal(puedeDescargarPliego({ estado: "no_analizable" }), true);
  assert.equal(puedeDescargarPliego({ estado: "cuarentena" }), true);
  assert.equal(puedeDescargarPliego({ estado: "limpio", disponible: true, paginas: null }), true);       // limpio pero sin texto: reintentar la lectura
  assert.equal(puedeDescargarPliego({ estado: "limpio", disponible: true, paginas: 12 }), false);
  assert.equal(puedeDescargarPliego({ estado: "infectado", disponible: false, paginas: null }), false);
});

test("lecturaPliego: páginas, bloques u hojas, con singular, y el aviso", () => {
  assert.equal(lecturaPliego({ disponible: true, paginas: 12, unidad: "página", aviso: "" }), "12 páginas");
  assert.equal(lecturaPliego({ disponible: true, paginas: 1, unidad: "página", aviso: "" }), "1 página");
  assert.equal(lecturaPliego({ disponible: true, paginas: 3, unidad: "bloque", aviso: "" }), "3 bloques");
  assert.equal(lecturaPliego({ disponible: true, paginas: 2, unidad: "hoja", aviso: "" }), "2 hojas");
  assert.match(lecturaPliego({ disponible: true, paginas: 4, unidad: "página", aviso: "parece un escaneo" }), /4 páginas · parece un escaneo/);
  assert.match(lecturaPliego({ disponible: true, paginas: null, aviso: "PDF roto" }), /No se ha podido leer el texto: PDF roto/);
  assert.equal(lecturaPliego({ disponible: false }), "");
  assert.equal(lecturaPliego(null), "");
});

test("requisitos: tipo, estado, resumen y lugar de la cita", () => {
  assert.equal(tipoRequisito("solvencia_economica"), "Solvencia económica");
  assert.equal(tipoRequisito("raro_x"), "raro x");
  assert.equal(estadoRequisito({ estado: "confirmado" }).clase, "abierta");
  assert.equal(estadoRequisito({ estado: "rechazado" }).clase, "anulada");
  assert.match(estadoRequisito({ estado: "borrador" }).texto, /pendiente de revisar/);
  assert.equal(resumenRequisitos([]), "Aún no hay requisitos anotados.");
  assert.equal(resumenRequisitos([{ estado: "borrador" }, { estado: "borrador" }, { estado: "confirmado" }]), "3 requisitos: 1 confirmado, 2 en borrador");
  assert.equal(resumenRequisitos([{ estado: "rechazado" }]), "1 requisito: 1 rechazado");
  assert.equal(lugarCita({ nombre: "Pliego administrativo", unidad: "página", pagina: 12, documento: 1 }), "Pliego administrativo, página 12");
  assert.equal(lugarCita({ documento: 2, pagina: 3 }), "Documento 2, página 3");
});

test("mensajePliegos: el motivo según el código", () => {
  assert.match(mensajePliegos(403), /Dirección y el departamento de Licitaciones/);
  assert.match(mensajePliegos(422), /no está bajado y analizado/);
  assert.match(mensajePliegos(503), /antivirus/);
  assert.match(mensajePliegos(500), /No se ha podido completar/);
});

import { celdaCsv, cumplimientoEtiqueta, cumplimientoNecesitaNota, matrizCsv, matrizDe, resumenMatriz } from "../lib/licitaciones.js";

test("matriz de cumplimiento: solo los confirmados, con su resumen", () => {
  const rs = [
    { id: 1, estado: "confirmado", cumplimiento: "cumple" }, { id: 2, estado: "confirmado", cumplimiento: "parcial" }, { id: 3, estado: "confirmado" },
    { id: 4, estado: "borrador" }, { id: 5, estado: "rechazado", cumplimiento: "cumple" },
  ];
  const m = matrizDe(rs);
  assert.equal(m.total, 3);
  assert.deepEqual(m.resumen, { pendiente: 1, cumple: 1, parcial: 1, no_cumple: 0, no_aplica: 0 });   // sin valor = pendiente; lo rechazado no cuenta
  assert.equal(m.borradores, 1);
  assert.equal(resumenMatriz(m), "3 requisitos: 1 cumple, 1 en parte, 1 pendiente");
  assert.match(resumenMatriz(matrizDe([])), /Aún no hay requisitos confirmados/);
  assert.equal(resumenMatriz(matrizDe([{ estado: "confirmado", cumplimiento: "no_cumple" }])), "1 requisito: 1 no cumple");
});

test("cumplimiento: etiquetas y cuándo hace falta el motivo", () => {
  assert.equal(cumplimientoEtiqueta("cumple").clase, "abierta");
  assert.equal(cumplimientoEtiqueta("no_cumple").clase, "anulada");
  assert.equal(cumplimientoEtiqueta("pendiente").texto, "Pendiente de valorar");
  assert.equal(cumplimientoNecesitaNota("parcial"), true);
  assert.equal(cumplimientoNecesitaNota("no_cumple"), true);
  assert.equal(cumplimientoNecesitaNota("cumple"), false);
});

test("CSV de la matriz: comillas dobladas, sin fórmulas y con los acentos intactos", () => {
  assert.equal(celdaCsv('dice "hola"'), '"dice ""hola"""');
  assert.equal(celdaCsv("=HYPERLINK(\"http://x\")"), "\"'=HYPERLINK(\"\"http://x\"\")\"");     // una hoja de cálculo no lo toma por fórmula
  assert.equal(celdaCsv("+34 600"), "\"'+34 600\"");
  assert.equal(celdaCsv("uno\ndos"), '"uno dos"');
  assert.equal(celdaCsv(null), '""');
  const csv = matrizCsv({ filas: [{ tipo: "solvencia_economica", resumen: "Volumen ≥ 300.000 €", valor: "300.000 €", cita: "igual o superior", nombre: "PCAP", unidad: "página", pagina: 4, documento: 1, cumplimiento: "parcial", cumplimiento_nota: "Faltan 50.000 €", cumplimiento_por: "ana" }] });
  assert.ok(csv.startsWith("﻿"));
  const lineas = csv.slice(1).split("\r\n");
  assert.equal(lineas.length, 2);
  assert.equal(lineas[1], '"Solvencia económica";"Volumen ≥ 300.000 €";"300.000 €";"igual o superior";"PCAP, página 4";"Cumple en parte";"Faltan 50.000 €";"ana"');
});

import { ganadoresTexto as ganadoresTextoNuevos, vigilaTexto as vigilaTextoNuevos } from "../lib/licitaciones.js";

test("alerta de nuevo competidor: se dice qué vigila y que la empresa es nueva", () => {
  assert.equal(vigilaTextoNuevos({ competidores: [], solo_nuevos: true }), "empresas nuevas en el mercado");
  assert.equal(vigilaTextoNuevos({ competidores: [], solo_nuevos: false }), "cualquier adjudicatario");
  assert.equal(vigilaTextoNuevos({ competidores: ["B12345678"], solo_nuevos: false }), "B12345678");
  const g = [{ nombre: "Seguridad SL", nif: "B12345678", importe: "90000.00", lote: "1" }];
  assert.ok(!ganadoresTextoNuevos({ ganadores: g })[0].includes("nueva"));
  assert.match(ganadoresTextoNuevos({ ganadores: g, nuevos: true })[0], /empresa nueva en este mercado$/);
});

import { aptitudSimulacion, costeDeTexto, filasDeCurva, mensajeSimulador, porcentaje, probabilidadConRango } from "../lib/licitaciones.js";

test("simulador: porcentajes, rangos y coste escrito", () => {
  assert.equal(porcentaje(0.456), "46 %");
  assert.equal(porcentaje(null), "—");
  assert.equal(probabilidadConRango({ p_ganar: 0.45, p_ganar_min: 0.3, p_ganar_max: 0.61 }), "45 % (30–61 %)");
  assert.equal(costeDeTexto("150.000"), 150000);
  assert.equal(costeDeTexto("150000,50"), 150000.5);
  assert.equal(costeDeTexto(" 1.234.567 € "), 1234567);
  assert.equal(costeDeTexto("12,5"), 12.5);
  assert.equal(costeDeTexto(""), null);
  assert.equal(costeDeTexto("mucho"), null);
  assert.equal(costeDeTexto("-5"), null);
  assert.equal(costeDeTexto("0"), null);
});

test("simulador: filas de la curva con la primera, la última y la recomendada", () => {
  const curva = Array.from({ length: 41 }, (_, i) => ({ baja_pct: i }));
  const f = filasDeCurva({ curva, recomendacion: { baja_pct: 17 } }, 10);
  assert.ok(f.length <= 11);
  assert.equal(f[0].baja_pct, 0);
  assert.equal(f.at(-1).baja_pct, 40);
  assert.ok(f.some((x) => x.baja_pct === 17));
  assert.deepEqual(filasDeCurva({ curva: curva.slice(0, 5) }), curva.slice(0, 5));
  assert.deepEqual(filasDeCurva(null), []);
});

test("simulador: cuándo es apto para decidir y cuándo solo orienta", () => {
  assert.equal(aptitudSimulacion({ apto_para_decidir: true }).apto, true);
  const a = aptitudSimulacion({ apto_para_decidir: false, muestra: { suficiente: false, n: 12 }, backtest: { apto: false, motivo: "muestra por debajo del mínimo" }, licitacion: { peso_juicio_de_valor: 40 } });
  assert.equal(a.apto, false);
  assert.match(a.texto, /orientativo/);
  assert.match(a.texto, /pocos concursos parecidos \(12\)/);
  assert.match(a.texto, /juicio de valor pesa un 40 %/);
  assert.equal(aptitudSimulacion(null).texto, "");
  assert.match(mensajeSimulador(403), /Dirección/);
  assert.match(mensajeSimulador(422), /sin concursos parecidos/);
});

test("la pasarela deja pasar «parecidas» solo de un expediente y solo con GET", () => {
  assert.ok(rutaPermitida(["tenders", ID, "parecidas"], "GET"));
  assert.ok(!rutaPermitida(["tenders", ID, "parecidas"], "POST"));
  assert.ok(!rutaPermitida(["tenders", "no-uuid", "parecidas"], "GET"));
  assert.ok(!rutaPermitida(["tenders", ID, "otra"], "GET"));
  assert.ok(!rutaPermitida(["tenders", ID, "parecidas", "x"], "GET"));
  assert.ok(!rutaPermitida(["organizations", ID, "parecidas"], "GET"));
});

test("modo de búsqueda: va a la dirección, exige texto y ignora el orden", () => {
  const p = filtrosAQuery({ ...FILTROS_VACIOS, q: "cámaras de seguridad", modo: "significado", orden: "plazo" });
  assert.equal(p.get("modo"), "significado");
  assert.equal(p.get("orden"), null);
  assert.equal(filtrosAQuery({ ...FILTROS_VACIOS, modo: "significado" }).get("modo"), null);      // sin texto no hay búsqueda por significado
  assert.equal(filtrosAQuery({ ...FILTROS_VACIOS, q: "obras", modo: "raro" }).get("modo"), null);
  assert.equal(filtrosAQuery({ ...FILTROS_VACIOS, q: "obras", orden: "plazo" }).get("orden"), "plazo");
  assert.equal(queryAFiltros(new URLSearchParams("q=obras&modo=hibrido")).modo, "hibrido");
  assert.equal(queryAFiltros(new URLSearchParams("q=obras&modo=raro")).modo, "");
});

test("cercanía y motivos se leen en castellano", () => {
  assert.equal(cercaniaTexto(0.834), "83 % de parecido");
  assert.equal(cercaniaTexto(undefined), "");
  assert.equal(cercaniaTexto(2), "");
  assert.equal(motivosTexto(["mismo_comprador", "cpv_comun", "raro"]), "Mismo comprador · CPV en común");
  assert.equal(motivosTexto(undefined), "");
  assert.match(mensajeParecidas(503), /Todavía no/);
});

test("reglas del pliego: del formulario al envío, con coma decimal y comprobaciones", () => {
  const ok = reglasAEnvio(ID, { formula: "inversa", puntos: "51,5", total: "", tope: "", anormal: "25", nota: " Cláusula 12 " });
  assert.deepEqual(ok.cuerpo, { motor_id: ID, formula: "inversa", puntos_precio: 51.5, puntos_total: 100, nota: "Cláusula 12", baja_anormal_pct: 25 });
  const lineal = reglasAEnvio(ID, { formula: "lineal_umbral", puntos: "40", total: "100", tope: "20", anormal: "" });
  assert.equal(lineal.cuerpo.baja_tope_pct, 20);
  assert.equal(lineal.cuerpo.baja_anormal_pct, undefined);
  for (const f of [{ formula: "rara", puntos: "5" }, { formula: "inversa", puntos: "" }, { formula: "inversa", puntos: "60", total: "50" }, { formula: "lineal_umbral", puntos: "40" },
    { formula: "lineal_umbral", puntos: "40", tope: "200" }, { formula: "inversa", puntos: "40", anormal: "abc" }]) {
    assert.ok(reglasAEnvio(ID, f).error, JSON.stringify(f));
  }
});

test("reglas guardadas → formulario, y mensajes", () => {
  assert.deepEqual(reglasAFormulario({ formula: "lineal_umbral", puntos_precio: 40.5, puntos_total: 100, baja_tope_pct: 20, baja_anormal_pct: null, nota: "x" }),
    { formula: "lineal_umbral", puntos: "40,5", total: "", tope: "20", anormal: "", nota: "x" });
  assert.equal(reglasAFormulario(null).formula, "inversa");
  assert.match(mensajeReglas(403), /Dirección/);
  assert.equal(mensajeSimulador(422, "No existe el presupuesto «X» en el ERP"), "No existe el presupuesto «X» en el ERP");
  assert.match(mensajeSimulador(422), /No se puede simular/);
});

test("coste del ERP en una frase", () => {
  assert.equal(costeErpTexto(null), "");
  assert.match(costeErpTexto({ presupuesto: "Q1", lineas: [1, 2], sin_coste: [] }), /2 líneas con coste\.$/);
  assert.match(costeErpTexto({ presupuesto: "Q1", lineas: [1], sin_sin: 0, sin_coste: [1] }), /1 línea con coste; 1 sin coste/);
});

test("oferta: etiquetas, autor, resumen y pendientes", () => {
  assert.equal(estadoSeccionEtiqueta("vacia"), "Sin redactar");
  assert.equal(estadoSeccionEtiqueta("aprobada"), "Aprobada");
  assert.equal(autorSeccionTexto({ por: "agente:redactor-memoria", version: 2 }), "Redactada por el agente redactor-memoria");
  assert.equal(autorSeccionTexto({ por: "marta", version: 1 }), "Escrita por marta");
  assert.equal(autorSeccionTexto({ por: "", version: 0 }), "");
  assert.equal(resumenOfertaTexto({ resumen: { vacia: 3, borrador: 1, revisada: 0, aprobada: 2 } }), "3 sin redactar · 1 borrador · 2 aprobadas");
  assert.equal(resumenOfertaTexto(null), "");
  const o = { existe: true, precio_sin_iva: null, cobertura: { sin_cubrir: [1, 2] }, secciones: [{ estado: "vacia" }, { estado: "borrador" }, { estado: "aprobada" }] };
  assert.deepEqual(pendientesOferta(o), ["1 sección sin redactar", "1 sección sin aprobar", "falta fijar el precio", "2 requisitos técnicos del pliego sin cubrir"]);
  assert.deepEqual(pendientesOferta({ existe: true, precio_sin_iva: 10, cobertura: { sin_cubrir: [] }, secciones: [{ estado: "aprobada" }] }), []);
  assert.deepEqual(pendientesOferta({ existe: false }), []);
});

test("oferta: el precio del formulario, con coma decimal y comprobaciones", () => {
  assert.deepEqual(precioAEnvio({ precio: "125.000,50", iva: "" }).cuerpo, { precio: 125000.5, iva_pct: 21 });
  assert.deepEqual(precioAEnvio({ precio: "90000", iva: "10" }).cuerpo, { precio: 90000, iva_pct: 10 });
  assert.deepEqual(precioAEnvio({ precio: "90000", iva: "0" }).cuerpo, { precio: 90000, iva_pct: 0 });
  for (const f of [{ precio: "" }, { precio: "abc" }, { precio: "-5" }, { precio: "100", iva: "150" }, { precio: "100", iva: "x" }]) assert.ok(precioAEnvio(f).error, JSON.stringify(f));
  assert.match(mensajeOferta(403), /Dirección/);
  assert.equal(mensajeOferta(422, "Esa sección ya está revisada"), "Esa sección ya está revisada");
  assert.match(mensajeOferta(500), /Inténtalo/);
});

import {
  COLUMNAS_ORDENABLES, calendarioPlazos, divisionEtiqueta, estadisticasQuery, filtroDesdeDashboard, hoyMadrid, importeCorto, repartoBarras, tramoEtiqueta, zonaEtiqueta,
} from "../lib/licitaciones.js";

test("la pasarela deja pasar las estadísticas del dashboard, solo con GET", () => {
  assert.ok(rutaPermitida(["tenders", "estadisticas"], "GET"));
  assert.ok(!rutaPermitida(["tenders", "estadisticas"], "POST"));
  assert.ok(!rutaPermitida(["tenders", "estadisticas", "x"], "GET"));
  assert.ok(!rutaPermitida(["tenders", "otra-cosa"], "GET"));
});

test("las estadísticas llevan los filtros de la búsqueda pero ni el orden ni el modo", () => {
  const f = { ...queryAFiltros(new URLSearchParams("q=cámaras&estado=abierta&nuts=ES512&orden=plazo&modo=significado&importe_min=1000")) };
  const q = estadisticasQuery(f);
  assert.equal(q.get("q"), "cámaras");
  assert.deepEqual(q.getAll("estado"), ["abierta"]);
  assert.deepEqual(q.getAll("nuts"), ["ES512"]);
  assert.equal(q.get("importe_min"), "1000");
  assert.equal(q.has("orden"), false);
  assert.equal(q.has("modo"), false);
});

test("importeCorto resume sin perder el orden de magnitud", () => {
  assert.equal(importeCorto("1500000"), "1,5 M€");
  assert.equal(importeCorto("250000"), "250 k€");
  assert.equal(importeCorto("980"), "980 €");
  assert.equal(importeCorto("0.00"), "0 €");
  for (const malo of ["", null, undefined, "abc", "1e9", "1,5"]) assert.equal(importeCorto(malo), "—");
});

test("etiquetas de zona, sector e importe: conocidas, desconocidas y vacías", () => {
  assert.equal(zonaEtiqueta("ES512"), "Girona (ES512)");
  assert.equal(zonaEtiqueta("FR101"), "FR101");
  assert.equal(zonaEtiqueta(""), "Sin zona");
  assert.equal(divisionEtiqueta("72"), "Servicios informáticos (72)");
  assert.equal(divisionEtiqueta("99"), "CPV 99");
  assert.equal(divisionEtiqueta(""), "Sin CPV");
  assert.equal(tramoEtiqueta("15k_50k"), "15.000 – 50.000 €");
  assert.equal(tramoEtiqueta("raro"), "raro");
});

test("repartoBarras escala a la mayor y aguanta lo que no es una lista", () => {
  const b = repartoBarras([{ valor: "a", cuenta: 10 }, { valor: "b", cuenta: 5 }, { valor: "c", cuenta: 0 }], (v) => v.toUpperCase());
  assert.deepEqual(b.map((x) => [x.etiqueta, x.pct]), [["A", 100], ["B", 50], ["C", 0]]);
  assert.deepEqual(repartoBarras([{ valor: "a", cuenta: 0 }]).map((x) => x.pct), [0]);
  assert.deepEqual(repartoBarras(null), []);
  assert.deepEqual(repartoBarras(undefined), []);
});

test("el calendario rellena con ceros los 60 días, empieza hoy y cruza meses y años", () => {
  const c = calendarioPlazos([{ valor: "2027-01-02", cuenta: 3 }, { valor: "2026-12-31", cuenta: 1 }], "2026-12-30", 60);
  assert.equal(c.length, 60);
  assert.equal(c[0].fecha, "2026-12-30");
  assert.equal(c[0].esHoy, true);
  assert.equal(c.filter((d) => d.esHoy).length, 1);
  assert.equal(c[1].cuenta, 1);
  assert.equal(c[3].fecha, "2027-01-02");
  assert.equal(c[3].cuenta, 3);
  assert.equal(c[3].pct, 100);
  assert.equal(c[1].pct, 33);
  assert.equal(c[59].fecha, "2027-02-27");
  assert.equal(c.reduce((a, d) => a + d.cuenta, 0), 4);
  assert.equal(calendarioPlazos(undefined, "2026-10-30", 3).every((d) => d.cuenta === 0 && d.pct === 0), true);
});

test("hoyMadrid da la fecha de Madrid aunque en UTC sea otro día", () => {
  assert.equal(hoyMadrid(new Date("2026-10-30T23:30:00Z")), "2026-10-31");   // 00:30 del día siguiente en Madrid (CET)
  assert.equal(hoyMadrid(new Date("2026-07-01T10:00:00Z")), "2026-07-01");
});

test("pulsar el dashboard cambia un solo filtro: estados se alternan, zona y CPV se fijan o se quitan", () => {
  const base = queryAFiltros(new URLSearchParams("q=red&estado=abierta"));
  const a = filtroDesdeDashboard(base, "estado", "cerrada");
  assert.deepEqual(a.estados, ["abierta", "cerrada"]);
  assert.deepEqual(filtroDesdeDashboard(a, "estado", "abierta").estados, ["cerrada"]);
  const z = filtroDesdeDashboard(base, "zona", "ES512");
  assert.equal(z.nuts, "ES512");
  assert.equal(filtroDesdeDashboard(z, "zona", "ES512").nuts, "");
  const c = filtroDesdeDashboard(base, "cpv", "72");
  assert.equal(c.cpv, "72");
  assert.equal(filtroDesdeDashboard(c, "cpv", "72").cpv, "");
  assert.equal(c.q, "red");                                  // lo demás se queda
  assert.deepEqual(filtroDesdeDashboard(base, "otra", "x"), base);
  assert.deepEqual(base.estados, ["abierta"]);               // y no toca el original
});

test("las columnas que se ordenan piden al motor órdenes que existen", () => {
  assert.deepEqual(Object.values(COLUMNAS_ORDENABLES).sort(), ["actualizacion", "importe", "plazo"]);
});

import {
  clasePaso, clasePlantilla, empresaParaEnviar, mensajeRedaccion, origenTexto, pasoEtiqueta, pendientesQueBloquean, plantillaEtiqueta, redaccionEnCurso, resumenPlantillas, resumenRedaccion,
} from "../lib/licitaciones.js";

test("la redacción con agentes solo se sondea mientras trabajan y se resume en una frase", () => {
  assert.equal(redaccionEnCurso({ estado: "en_curso" }), true);
  for (const e of [{ estado: "completa" }, { estado: "parcial" }, { estado: "error" }, null, undefined]) assert.equal(redaccionEnCurso(e), false);
  const pasos = (...estados) => estados.map((estado, i) => ({ id: `p${i}`, estado }));
  assert.equal(resumenRedaccion({ estado: "en_curso", pasos: pasos("hecho", "en_curso", "pendiente", "pendiente") }), "En curso: 1 de 4 pasos");
  assert.equal(resumenRedaccion({ estado: "completa", pasos: pasos("hecho", "hecho", "omitido") }), "Terminada: 2 hechos, 1 sin nada que hacer");
  assert.equal(resumenRedaccion({ estado: "parcial", pasos: pasos("hecho", "parcial", "error") }), "Terminada a medias: 1 hecho, 1 a medias, 1 con error");
  assert.equal(resumenRedaccion({ estado: "error", pasos: pasos("pendiente", "pendiente") }), "No se ha podido hacer: 2 sin hacer");
  assert.equal(resumenRedaccion({ estado: "completa", pasos: [] }), "");
  assert.equal(resumenRedaccion(null), "");
});

test("etiquetas y colores de los pasos y de las plantillas", () => {
  assert.equal(pasoEtiqueta("en_curso"), "Trabajando…");
  assert.equal(pasoEtiqueta("raro"), "raro");
  assert.equal(clasePaso("hecho"), "abierta");
  assert.equal(clasePaso("error"), "anulada");
  assert.equal(clasePaso("parcial"), "aviso");
  assert.equal(plantillaEtiqueta("lista_para_firma"), "Lista para firmar");
  assert.equal(plantillaEtiqueta("faltan_datos"), "Faltan datos");
  assert.equal(clasePlantilla("lista_para_firma"), "abierta");
  assert.equal(clasePlantilla("faltan_datos"), "aviso");
});

test("de las plantillas solo bloquea lo que impide firmar; la fecha se completa al firmar", () => {
  const d = { pendientes: [{ id: "t1", bloquea: true }, { id: "t2", bloquea: false }, { id: "c3", bloquea: true }] };
  assert.deepEqual(pendientesQueBloquean(d).map((p) => p.id), ["t1", "c3"]);
  assert.deepEqual(pendientesQueBloquean({}), []);
  assert.deepEqual(pendientesQueBloquean(null), []);
  assert.equal(resumenPlantillas({ resumen: { lista_para_firma: 2, faltan_datos: 1, sin_huecos: 0, error: 0 } }), "2 listas para firmar · 1 con datos pendientes");
  assert.equal(resumenPlantillas({ resumen: { lista_para_firma: 1, faltan_datos: 0, sin_huecos: 0, error: 1 } }), "1 lista para firmar · 1 con error");
  assert.equal(resumenPlantillas({ resumen: { lista_para_firma: 0, faltan_datos: 0, sin_huecos: 0, error: 0 } }), "");
  assert.equal(resumenPlantillas(null), "");
});

test("el origen de un dato dice de qué campo del ERP sale", () => {
  assert.equal(origenTexto("ERP · Company 101 Telecom S.L. · tax_id"), "ERP: tax_id de 101 Telecom S.L.");
  assert.equal(origenTexto("Motor de licitaciones · ficha"), "Motor de licitaciones · ficha");
  assert.equal(origenTexto(null), "");
});

test("la sociedad que se manda: la elegida, o la ya guardada en la oferta, o ninguna", () => {
  assert.equal(empresaParaEnviar("Ion S.A.", "101 S.L."), "Ion S.A.");
  assert.equal(empresaParaEnviar("", "101 S.L."), "101 S.L.");
  assert.equal(empresaParaEnviar("", null), undefined);
  assert.equal(empresaParaEnviar(undefined, undefined), undefined);
});

test("los mensajes de la redacción explican qué hacer", () => {
  assert.match(mensajeRedaccion(403), /Dirección/);
  assert.equal(mensajeRedaccion(409, "Los agentes ya están trabajando en esta oferta"), "Los agentes ya están trabajando en esta oferta");
  assert.match(mensajeRedaccion(409), /Ya se está trabajando/);
  assert.equal(mensajeRedaccion(422, "El documento 7 no está bajado"), "El documento 7 no está bajado");
  assert.match(mensajeRedaccion(503), /ERP|motor|cola/);
  assert.match(mensajeRedaccion(500), /Inténtalo de nuevo/);
});
