import test from "node:test";
import assert from "node:assert/strict";
import {
  antiguedadTexto, conAcceso, decidir, estadoEtiqueta, estadoMotor, filtrosAQuery, fechaTexto, importeTexto, limpiarCpv, limpiarNuts, mensajeDeError,
  nombreFuente, queryAFiltros, rutaPermitida, totalTexto, urlSegura,
} from "../lib/licitaciones.js";
import { ambitoTexto, eventoEtiqueta, filtroDeAlerta, filtroTexto, mensajeAlertas, sinLeerTexto } from "../lib/licitaciones.js";
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
  const f = { q: "software", cpv: "72 35", nuts: "ES512", estados: ["abierta", "cerrada"], importeMin: "100", importeMax: "", orden: "importe", plazoHasta: "2026-12-01" };
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
