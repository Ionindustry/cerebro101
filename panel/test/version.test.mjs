import test from "node:test";
import assert from "node:assert/strict";
import { textoVersion, versionCorta } from "../lib/version.js";

test("versión corta: 7 caracteres del commit o «desconocida»", () => {
  assert.equal(versionCorta("F13D2AA4F39C41150577E59DCA3A84E4A0CE8F9D"), "f13d2aa");
  assert.equal(versionCorta("f13d2aa"), "f13d2aa");
  for (const v of [undefined, null, "", "desconocida", "xyz", "12345"]) assert.equal(versionCorta(v), "desconocida");
});

test("texto de versión: aviso solo si panel y API difieren y ambas se conocen", () => {
  assert.deepEqual(textoVersion("f13d2aa1", "f13d2aa9"), { texto: "Versión f13d2aa", aviso: "" });
  const d = textoVersion("f13d2aa", "90f3543");
  assert.match(d.texto, /f13d2aa · la API lleva 90f3543/);
  assert.match(d.aviso, /actualizar\.sh/);
  assert.equal(textoVersion("desconocida", "90f3543").aviso, "");
  assert.equal(textoVersion("f13d2aa", null).texto, "Versión f13d2aa");
  assert.equal(textoVersion("f13d2aa", "desconocida").aviso, "");
});
