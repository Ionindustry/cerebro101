import assert from "node:assert/strict";
import test from "node:test";
import { barras, etiquetaDia, formatearDelta, formatearValor, segmentos, unidadVisible } from "../lib/kpi.js";

test("formatea importes, porcentajes y tiempos", () => {
  assert.match(formatearValor(12345.6, "€"), /12\.346\s?€/);
  assert.equal(formatearValor(80, "%"), "80 %");
  assert.equal(formatearValor(10, "min"), "10 min");
  assert.equal(formatearValor(180, "min"), "3 h");
  assert.equal(formatearValor(3, "leads"), "3");
  assert.equal(formatearValor(null, "€"), "—");
  assert.equal(formatearValor(0, "€").replace(/\s/g, ""), "0€");
});

test("la unidad solo se muestra cuando no va ya en el número", () => {
  assert.equal(unidadVisible("€"), "");
  assert.equal(unidadVisible("leads"), "leads");
});

test("delta: sube, baja, igual y sin dato", () => {
  assert.deepEqual(formatearDelta(25), { texto: "▲ +25 %", signo: 1 });
  assert.deepEqual(formatearDelta(-10), { texto: "▼ -10 %", signo: -1 });
  assert.equal(formatearDelta(0).signo, 0);
  assert.equal(formatearDelta(null), null);
});

test("las barras escalan al máximo y un valor pequeño se ve", () => {
  const b = barras([{ dia: "2026-10-24", n: 100 }, { dia: "2026-10-25", n: 1 }, { dia: "2026-10-26", n: 0 }], "n", 100);
  assert.deepEqual(b.map((x) => x.altura), [100, 3, 0]);
  assert.deepEqual(barras([{ n: 0 }], "n").map((x) => x.altura), [0]);
});

test("etiquetas de día y segmentos", () => {
  assert.equal(etiquetaDia("2026-10-05"), "5/10");
  const s = segmentos([{ n: 2 }, { n: 1 }, { n: 1 }]);
  assert.deepEqual(s.map((x) => x.ancho), [50, 25, 25]);
  assert.deepEqual(segmentos([{ n: 0 }]), []);
});
