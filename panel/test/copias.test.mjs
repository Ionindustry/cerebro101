import test from "node:test";
import assert from "node:assert/strict";
import { copiasResumen } from "../lib/copias.js";

const bien = { fecha: "2026-11-04T13:00:00Z", bytes: 5_300_000, ok: true, mensaje: "" };

test("tarjeta de copias: al día, con la restauración probada o sin probar", () => {
  const a = copiasResumen({ ultima: bien, ultima_correcta: bien, restauracion: { ...bien, ok: true }, dias_sin_copia: 0.5, alerta: false, dias_limite: 3 });
  assert.deepEqual([a.nivel, a.titulo], ["bien", "al día"]);
  assert.match(a.lineas[0], /5\.3 MB/);
  const b = copiasResumen({ ultima: bien, ultima_correcta: bien, restauracion: null, dias_sin_copia: 0.5, alerta: false, dias_limite: 3 });
  assert.deepEqual([b.nivel, b.titulo], ["aviso", "al día (restauración sin probar)"]);
  assert.match(b.lineas.join(" "), /probar_restauracion/);
});

test("tarjeta de copias: fallos, alerta de días y sin datos", () => {
  const f = copiasResumen({ ultima: { ...bien, ok: false, mensaje: "pg_dump: error" }, ultima_correcta: bien, restauracion: null, dias_sin_copia: 1, alerta: false, dias_limite: 3 });
  assert.deepEqual([f.nivel, f.titulo], ["aviso", "la última copia falló"]);
  assert.match(f.lineas.join(" "), /FALLÓ.*pg_dump: error/);
  const d = copiasResumen({ ultima: bien, ultima_correcta: bien, restauracion: null, dias_sin_copia: 4.2, alerta: true, dias_limite: 3 });
  assert.deepEqual([d.nivel, d.titulo], ["mal", "llevas 4 días sin una correcta"]);
  const r = copiasResumen({ ultima: bien, ultima_correcta: bien, restauracion: { ...bien, ok: false, mensaje: "no se restaura" }, dias_sin_copia: 1, alerta: false, dias_limite: 3 });
  assert.equal(r.titulo, "la copia no se puede restaurar");
  assert.equal(copiasResumen({ ultima: null, ultima_correcta: null, restauracion: null, dias_sin_copia: null, alerta: false, dias_limite: 3 }).titulo, "sin copias todavía");
  assert.equal(copiasResumen(null).titulo, "sin datos");
});
