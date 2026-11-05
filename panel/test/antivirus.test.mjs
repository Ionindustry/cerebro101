import test from "node:test";
import assert from "node:assert/strict";
import { antivirusResumen } from "../lib/antivirus.js";

const base = { version: "ClamAV 1.4.6/28173/Tue Nov  3 06:27:52 2026", fecha_firmas: "2026-11-03T06:27:52+00:00", aviso_horas: 36, limite_horas: 48, motivo: "" };

test("tarjeta del antivirus: al día, firmas viejas con y sin rechazo, sin respuesta y sin datos", () => {
  const a = antivirusResumen({ ...base, estado: "ok", edad_horas: 5.2 });
  assert.deepEqual([a.nivel, a.titulo, a.ayuda], ["bien", "firmas al día (hace 5 h)", null]);
  const b = antivirusResumen({ ...base, estado: "viejas", edad_horas: 40, motivo: "Las firmas del antivirus tienen 40 horas" });
  assert.deepEqual([b.nivel, b.titulo], ["aviso", "firmas viejas"]);
  assert.match(b.ayuda, /freshclam/);
  const c = antivirusResumen({ ...base, estado: "viejas", edad_horas: 53.5, motivo: "ya se rechazan" });
  assert.deepEqual([c.nivel, c.titulo], ["mal", "firmas viejas: se rechazan los documentos"]);
  const d = antivirusResumen({ ...base, estado: "no_responde", version: null, fecha_firmas: null, edad_horas: null, motivo: "El antivirus no responde" });
  assert.deepEqual([d.nivel, d.titulo], ["mal", "no responde"]);
  assert.equal(antivirusResumen({ ...base, estado: "viejas", fecha_firmas: null, edad_horas: null }).nivel, "mal");
  assert.equal(antivirusResumen(null).titulo, "sin datos");
});
