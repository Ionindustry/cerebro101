import test from "node:test";
import assert from "node:assert/strict";
import { agruparRequisitos, lecturaEnMarcha, lecturaTexto, datoAnalisisTexto, activableMotivo, ejecucionTexto, fechaCorta, filtrosAQuery, importeTexto, mensajeError, plazoTexto, urlSegura, FILTROS_VACIOS, GRUPOS_ESTADO, grupoActivo } from "../lib/subvenciones.js";

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

test("los tres botones de estado envían sus estados y se reconocen", () => {
  const por = (k) => GRUPOS_ESTADO.find((g) => g.clave === k).estados;
  assert.deepEqual(por("abiertas"), ["OPEN", "CLOSING_SOON"]);
  assert.deepEqual(por("por_abrir"), ["OPENING_SOON"]);
  const q = new URLSearchParams(filtrosAQuery({ ...FILTROS_VACIOS, estado: por("abiertas") }).slice(1));
  assert.deepEqual(q.getAll("estado"), ["OPEN", "CLOSING_SOON"]);
  assert.equal(grupoActivo(["CLOSING_SOON", "OPEN"]), "abiertas");
  assert.equal(grupoActivo(por("cerradas")), "cerradas");
  assert.equal(grupoActivo(""), "");
  assert.equal(filtrosAQuery({ ...FILTROS_VACIOS, estado: "" }), "");
});

test("la pasarela /cerebro reenvía todos los métodos que usa la página (Activar usa PATCH; Seguir, PUT; Dejar de seguir, DELETE)", async () => {
  const { readFileSync } = await import("node:fs");
  const ruta = readFileSync(new URL("../app/cerebro/[...ruta]/route.js", import.meta.url), "utf8");
  const pagina = readFileSync(new URL("../app/subvenciones/page.js", import.meta.url), "utf8");
  const usados = new Set([...pagina.matchAll(/enviar\("(PATCH|PUT|POST|DELETE)"/g)].map((m) => m[1]));
  if (/method: "DELETE"/.test(pagina)) usados.add("DELETE");
  assert.ok(usados.has("PATCH") && usados.has("PUT") && usados.has("DELETE"));
  for (const m of usados) assert.match(ruta, new RegExp(`reenviar as ${m}\\b`), `falta exportar ${m} en la pasarela`);
});

test("el análisis dice «No consta» cuando falta un dato y formatea listas, calendarios e importes", () => {
  assert.equal(datoAnalisisTexto({ consta: false, valor: null }), "No consta en la fuente");
  assert.equal(datoAnalisisTexto(undefined), "No consta en la fuente");
  assert.equal(datoAnalisisTexto({ consta: true, valor: ["PYME", "Autónomos"] }), "PYME, Autónomos");
  assert.equal(datoAnalisisTexto({ consta: true, valor: { apertura: "2026-11-01", fin_de_plazo: "2026-12-31" } }), "apertura: 2026-11-01 · fin de plazo: 2026-12-31");
  assert.equal(datoAnalisisTexto({ consta: true, valor: { maximo: "12000", moneda: "EUR" } }), "máximo: 12000 · moneda: EUR");
  assert.equal(datoAnalisisTexto({ consta: true, valor: true }), "Sí");
});

test("la lectura de bases: estados, texto y requisitos agrupados por tipo con los rechazados al final", () => {
  assert.equal(lecturaEnMarcha({ state: "en_cola" }), true);
  assert.equal(lecturaEnMarcha({ state: "ok" }), false);
  assert.equal(lecturaEnMarcha(null), false);
  assert.match(lecturaTexto(null), /Todavía no/);
  assert.match(lecturaTexto({ state: "error", reason: "modelo caído" }), /modelo caído/);
  assert.match(lecturaTexto({ state: "ok", stats: { documentos: 2, leidos: 1, requisitos: 5 } }), /1 de 2 documentos leídos, 5 requisitos nuevos/);
  const g = agruparRequisitos([{ id: 1, tipo: "plazo", estado: "rechazado" }, { id: 2, tipo: "plazo", estado: "borrador" }, { id: 3, tipo: "beneficiario", estado: "borrador" }, { id: 4, tipo: "raro", estado: "borrador" }]);
  assert.deepEqual(g.map(([t]) => t), ["beneficiario", "plazo", "otro"]);
  assert.deepEqual(g[1][1].map((r) => r.id), [2, 1]);
});
