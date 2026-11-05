import test from "node:test";
import assert from "node:assert/strict";
import { hoyResumen, hrefSeguro } from "../lib/hoy.js";

const it = (nivel, titulo, extra = {}) => ({ nivel, categoria: "licitaciones", titulo, detalle: "", href: "/licitaciones", ...extra });

test("hoy: titular y grupos por urgencia", () => {
  const r = hoyResumen({ urgentes: 2, items: [it("info", "c"), it("urgente", "a"), it("aviso", "b"), it("urgente", "a2")] });
  assert.equal(r.titular, "2 cosas urgentes y 1 más por mirar.");
  assert.deepEqual(r.grupos.map((g) => [g.nivel, g.items.length]), [["urgente", 2], ["aviso", 1], ["info", 1]]);
  assert.equal(r.vacio, false);
  assert.equal(hoyResumen({ urgentes: 1, items: [it("urgente", "a")] }).titular, "1 cosa urgente.");
  assert.equal(hoyResumen({ urgentes: 0, items: [it("aviso", "a"), it("aviso", "b")] }).titular, "2 cosas por mirar.");
  assert.equal(hoyResumen({ urgentes: 0, items: [it("info", "a")] }).titular, "Nada urgente; solo novedades.");
});

test("hoy: vacío, error y avisos de fuentes", () => {
  const v = hoyResumen({ urgentes: 0, items: [] });
  assert.deepEqual([v.vacio, v.titular, v.grupos], [true, "Todo al día: no hay nada pendiente.", []]);
  assert.equal(hoyResumen(null).titular, "No se ha podido cargar la lista de hoy.");
  assert.deepEqual(hoyResumen({ items: [], avisos: ["No se ha podido leer: antivirus"] }).avisos, ["No se ha podido leer: antivirus"]);
});

test("hoy: solo se enlazan rutas internas del panel", () => {
  assert.equal(hrefSeguro("/licitaciones/expedientes/0b1f-22"), "/licitaciones/expedientes/0b1f-22");
  assert.equal(hrefSeguro("/aprobaciones"), "/aprobaciones");
  for (const malo of ["https://malo.com", "//malo.com", "//malo", "javascript:alert(1)", "/a?x=1", "licitaciones", null, 5]) assert.equal(hrefSeguro(malo), null, String(malo));
});
