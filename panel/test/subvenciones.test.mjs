import test from "node:test";
import assert from "node:assert/strict";
import { activableMotivo, ejecucionTexto, fechaCorta, filtrosAQuery, importeTexto, mensajeError, plazoTexto, urlSegura, FILTROS_VACIOS } from "../lib/subvenciones.js";

test("solo se enlazan direcciones http(s)", () => {
  assert.equal(urlSegura("https://www.infosubvenciones.es/x"), "https://www.infosubvenciones.es/x");
  assert.equal(urlSegura("javascript:alert(1)"), null);
  assert.equal(urlSegura("data:text/html,x"), null);
  assert.equal(urlSegura(""), null);
  assert.equal(urlSegura(null), null);
});

test("plazoTexto cuenta días en calendario", () => {
  const ahora = Date.UTC(2026, 5, 10, 15, 0);
  assert.equal(plazoTexto("2026-06-10", ahora), "cierra hoy");
  assert.equal(plazoTexto("2026-06-11", ahora), "cierra mañana");
  assert.equal(plazoTexto("2026-06-15", ahora), "cierra en 5 días");
  assert.equal(plazoTexto("2026-06-09", ahora), "cerró ayer");
  assert.equal(plazoTexto("2026-06-01", ahora), "cerró hace 9 días");
  assert.equal(plazoTexto(null, ahora), "sin plazo publicado");
});

test("fechas e importes", () => {
  assert.equal(fechaCorta("2026-03-07"), "07/03/2026");
  assert.equal(fechaCorta("2026-03-07T10:00:00Z"), "07/03/2026");
  assert.equal(fechaCorta(null), "—");
  assert.equal(importeTexto(null), "—");
  assert.equal(importeTexto("abc"), "—");
  assert.match(importeTexto(1500000), /1\.500\.000/);
});

test("filtrosAQuery solo envía lo rellenado", () => {
  assert.equal(filtrosAQuery(FILTROS_VACIOS), "");
  const q = filtrosAQuery({ ...FILTROS_VACIOS, texto: " digital ", estado: "OPEN", importeMin: "1000", soloNuevas: true }, 2);
  const p = new URLSearchParams(q.slice(1));
  assert.equal(p.get("texto"), "digital");
  assert.equal(p.get("estado"), "OPEN");
  assert.equal(p.get("importe_min"), "1000");
  assert.equal(p.get("solo_nuevas"), "true");
  assert.equal(p.get("pagina"), "2");
  assert.equal(p.has("pais"), false);
});

test("una fuente sin conector o sin sincronización correcta no es activable", () => {
  assert.match(activableMotivo({ has_connector: false }), /conector/);
  assert.match(activableMotivo({ has_connector: true, last_success_at: null }), /manual/);
  assert.equal(activableMotivo({ has_connector: true, last_success_at: "2026-01-01T00:00:00Z" }), "");
  assert.ok(activableMotivo(null));
});

test("ejecución y errores", () => {
  assert.equal(ejecucionTexto({}), "Sin ejecuciones todavía");
  assert.match(ejecucionTexto({ run_status: "ok", fetched: 10, inserted: 3, updated: 1, unchanged: 6, invalid: 2 }), /Correcta: 10 leídos · 3 nuevos · 1 modificados · 6 sin cambios · 2 inválidos/);
  assert.match(mensajeError({ status: 403 }), /Dirección/);
  assert.equal(mensajeError({ status: 422, detalle: "x" }), "x");
});
