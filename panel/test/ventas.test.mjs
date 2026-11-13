import test from "node:test";
import assert from "node:assert/strict";
import { importeVentas, rankingTexto, resumenTipo, unidadesTexto } from "../lib/ventas.js";

test("importes y unidades se muestran en formato español", () => {
  assert.match(importeVentas("1234.5").replace(/\s/g, " "), /^1\.?234,50 €$/);
  assert.equal(importeVentas(null), "—");
  assert.equal(unidadesTexto("12.00"), "12");
  assert.equal(unidadesTexto("2.50"), "2,5");
});

test("resumenTipo y rankingTexto", () => {
  const t = { tipo: "cctv", nombre: "CCTV", importe: "100.00", cuota_pct: "50.00", pedidos: 1, unidades: "2", articulos: [{ codigo: "C1", nombre: "Cámara", marca: "Axis", importe: "100.00", unidades: "2.00" }], fabricantes: [{ nombre: "Axis", importe: "100.00", unidades: "2" }] };
  assert.match(resumenTipo(t), /CCTV · .*€ · 50 % · 1 pedido$/);
  const x = rankingTexto({ desde: "a", hasta: "b", total: "100.00", tipos: [t] });
  assert.match(x, /1\. Cámara \(C1\) · Axis/);
  assert.match(x, /Fabricantes:\n  1\. Axis/);
  assert.equal(rankingTexto({ tipos: [] }), "Sin ventas en el periodo.");
});
