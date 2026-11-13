import test from "node:test";
import assert from "node:assert/strict";
import { consultaLineas, euros, margenTexto, precioAEnvio, resumenPropuestaTexto } from "../lib/precios.js";

test("precioAEnvio acepta precios normales y rechaza lo raro", () => {
  assert.equal(precioAEnvio("199,5"), 199.5);
  assert.equal(precioAEnvio(" 1 234,50 "), 1234.5);
  for (const malo of ["", "abc", "-5", "0", "12,345", "1e3", "99999999999", null]) assert.equal(precioAEnvio(malo), null, String(malo));
});

test("formatos de margen e importe", () => {
  assert.equal(margenTexto("0.5000").replace(/\s/g, " "), "50,0 %");
  assert.equal(margenTexto(null), "—");
  assert.equal(euros("1234.5").replace(/\s/g, " "), "1234,50 €");
  assert.equal(euros(""), "—");
});

test("resumen de una propuesta", () => {
  assert.equal(resumenPropuestaTexto({ incluidos: 10, nuevo: 3, sube: 0, baja: 2, ajustados: 1, bajo_minimo: 0 }), "10 artículos · 3 nuevos · 2 bajan · 1 ajustados a mano");
  assert.equal(resumenPropuestaTexto(null), "");
});

test("consultaLineas solo lleva lo que tiene valor", () => {
  assert.equal(consultaLineas({}, 1), "");
  assert.equal(consultaLineas({ familia: "Cámaras", texto: "domo", bajoMinimo: true }, 2), "?familia=C%C3%A1maras&q=domo&bajo_minimo=true&pagina=2");
});

test("cambios de una tarifa y hace cuánto", async () => {
  const { cambiosTarifaTexto, haceTexto } = await import("../lib/precios.js");
  assert.equal(cambiosTarifaTexto({ articulos: 10, primera: true }), "10 artículos (primera tarifa de este proveedor: no hay con qué comparar)");
  assert.equal(cambiosTarifaTexto({ articulos: 120, nuevos: 5, retirados: 0, suben: 40, bajan: 12, iguales: 63, variacion_media_pct: "2.3" }), "120 artículos · 5 nuevos · 40 suben · 12 bajan · 63 iguales · variación media 2,3 %");
  assert.equal(cambiosTarifaTexto(null), "");
  const ahora = Date.parse("2026-11-13T12:00:00Z");
  assert.equal(haceTexto("2026-11-13T11:59:30Z", ahora), "ahora mismo");
  assert.equal(haceTexto("2026-11-13T09:00:00Z", ahora), "hace 3 h");
  assert.equal(haceTexto("2026-11-10T12:00:00Z", ahora), "hace 3 días");
  assert.equal(haceTexto(null, ahora), "nunca");
});
