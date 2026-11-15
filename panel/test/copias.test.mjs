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

import { ajustesAEnvio, ajustesAFormulario, resumenAjustesCopias } from "../lib/copias.js";

test("ajustes de copias: del servidor al formulario y de vuelta", () => {
  const f = ajustesAFormulario({ valores: { conservar: 7, extra: "", conservar_extra: 0, dias_aviso: 3 } });
  assert.deepEqual(f, { conservar: "7", extra: "", conservar_extra: "0", dias_aviso: "3" });
  assert.deepEqual(ajustesAFormulario(null), { conservar: "7", extra: "", conservar_extra: "0", dias_aviso: "3" });
  assert.deepEqual(ajustesAEnvio({ conservar: " 10 ", extra: " /mnt/d/Copias101/ ", conservar_extra: "30", dias_aviso: "2" }).cuerpo, { conservar: 10, extra: "/mnt/d/Copias101", conservar_extra: 30, dias_aviso: 2 });
  assert.deepEqual(ajustesAEnvio({ ...f, extra: "" }).cuerpo.extra, "");
});

test("ajustes de copias: lo que no vale se explica", () => {
  const f = { conservar: "7", extra: "", conservar_extra: "0", dias_aviso: "3" };
  for (const [clave, malo] of [["conservar", "0"], ["conservar", "61"], ["conservar", "abc"], ["conservar_extra", "366"], ["conservar_extra", "-1"], ["dias_aviso", "0"], ["dias_aviso", "15"], ["dias_aviso", ""]]) {
    assert.ok(ajustesAEnvio({ ...f, [clave]: malo }).error, `${clave}=${malo}`);
  }
  for (const ruta of ["/", "/etc", "/mnt/d", "/mnt/d/a b", "/mnt/d/../etc", "relativa", "/tmp/x", "/mnt/d/a;b"]) {
    assert.match(ajustesAEnvio({ ...f, extra: ruta }).error, /carpeta del servidor/, ruta);
  }
});

test("resumen de los ajustes en una frase", () => {
  assert.match(resumenAjustesCopias({ conservar: "7", extra: "", conservar_extra: "0", dias_aviso: "3" }), /sin segunda copia.*3 días/);
  assert.match(resumenAjustesCopias({ conservar: "7", extra: "/mnt/d/C", conservar_extra: "0", dias_aviso: "3" }), /allí no se borra nada/);
  assert.match(resumenAjustesCopias({ conservar: "7", extra: "/mnt/d/C", conservar_extra: "30", dias_aviso: "3" }), /las últimas 30/);
});
