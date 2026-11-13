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
