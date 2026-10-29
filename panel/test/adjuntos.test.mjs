import test from "node:test";
import assert from "node:assert/strict";
import { aBase64, estadoAdjuntoTexto, idsParaMensaje, mensajeSubida, textoConAdjuntos, validarAdjunto } from "../lib/adjuntos.js";

test("validarAdjunto: formatos, vacío y tamaño", () => {
  assert.equal(validarAdjunto({ name: "Tarifa 2026.XLSX", size: 1000 }), null);
  assert.equal(validarAdjunto({ name: "a.csv", size: 10 }), null);
  assert.match(validarAdjunto({ name: "a.xls", size: 10 }), /antiguo/);
  assert.match(validarAdjunto({ name: "a.zip", size: 10 }), /no admitido/);
  assert.match(validarAdjunto({ name: "a.exe", size: 10 }), /no admitido/);
  assert.match(validarAdjunto({ name: "a.pdf", size: 0 }), /vacío/);
  assert.match(validarAdjunto({ name: "a.pdf", size: 26_000_000 }), /25 MB/);
  assert.ok(validarAdjunto(null));
});

test("aBase64 coincide con Buffer y aguanta ficheros grandes", () => {
  const pequeño = new TextEncoder().encode("hola, ñandú").buffer;
  assert.equal(aBase64(pequeño), Buffer.from(pequeño).toString("base64"));
  const grande = new Uint8Array(3_000_000).map((_, i) => i % 251).buffer;
  assert.equal(aBase64(grande), Buffer.from(grande).toString("base64"));
});

test("mensajes y estado del adjunto", () => {
  assert.equal(mensajeSubida(422, "Formato no admitido"), "Formato no admitido");
  assert.match(mensajeSubida(413), /25 MB/);
  assert.match(mensajeSubida(401), /sesión/);
  assert.match(mensajeSubida(500), /Inténtalo/);
  assert.equal(estadoAdjuntoTexto({ disponible: true, paginas: 3, unidad: "página" }), "3 páginas");
  assert.equal(estadoAdjuntoTexto({ disponible: true, paginas: 1, unidad: "hoja" }), "1 hoja");
  assert.equal(estadoAdjuntoTexto({ disponible: false, estado: "infectado" }), "descartado por el antivirus");
  assert.equal(estadoAdjuntoTexto({ disponible: false, estado: "no_analizable", motivo: "antivirus caído" }), "antivirus caído");
  assert.equal(estadoAdjuntoTexto(null), "");
});

test("lo que se manda con el mensaje", () => {
  const a = [{ id: "1", nombre: "t.csv", disponible: true }, { id: "1", nombre: "t.csv", disponible: true }, { id: "2", nombre: "x.pdf", disponible: false }, { id: "3", nombre: "u.xlsx", disponible: true }];
  assert.deepEqual(idsParaMensaje(a), ["1", "3"]);
  assert.deepEqual(idsParaMensaje(null), []);
  assert.equal(textoConAdjuntos("importa esto", a), "importa esto\n📎 t.csv\n📎 t.csv\n📎 u.xlsx");
  assert.equal(textoConAdjuntos("hola", []), "hola");
});

test("la subida de documentos queda fuera del middleware (recorta cuerpos de más de 10 MB) pero el resto sigue dentro", async () => {
  const { readFile } = await import("node:fs/promises");
  const fuente = await readFile(new URL("../middleware.js", import.meta.url), "utf8");
  const patron = fuente.match(/matcher:\s*\["([^"]+)"\]/)[1];
  const re = new RegExp("^" + patron + "$");
  assert.equal(re.test("/cerebro/documentos/subir"), false);
  for (const ruta of ["/cerebro/jarvis/mensaje", "/cerebro/documentos/otro", "/licitaciones", "/"]) assert.equal(re.test(ruta), true, ruta);
});
