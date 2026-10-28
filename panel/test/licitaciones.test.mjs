import test from "node:test";
import assert from "node:assert/strict";
import {
  antiguedadTexto, conAcceso, decidir, estadoEtiqueta, estadoMotor, filtrosAQuery, fechaTexto, importeTexto, limpiarCpv, limpiarNuts, mensajeDeError,
  nombreFuente, queryAFiltros, rutaPermitida, totalTexto, urlSegura,
} from "../lib/licitaciones.js";

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
