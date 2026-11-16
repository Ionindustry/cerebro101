import test from "node:test";
import assert from "node:assert/strict";
import { fuenteTexto, mensajeMarcas, resumenMarca, resumenProveedor, variantesTexto } from "../lib/proveedoresMarcas.js";

test("de dónde sale cada marca", () => {
  assert.equal(fuenteTexto(["tarifa"]), "Tarifa");
  assert.equal(fuenteTexto(["manual"]), "A mano");
  assert.equal(fuenteTexto(["tarifa", "manual"]), "Tarifa y a mano");
  assert.equal(fuenteTexto([]), "—");
  assert.equal(fuenteTexto(null), "—");
});

test("líneas de proveedor y de marca", () => {
  assert.match(resumenProveedor({ proveedor: "A-Secur", articulos: 3265, marcas: new Array(29).fill({}) }).replace(/\s/g, " "), /^A-Secur · 29 marcas · 3\.?265 artículos$/);
  assert.match(resumenProveedor({ proveedor: "X", articulos: 1, marcas: [{}] }), /1 marca ·/);
  assert.match(resumenMarca({ marca: "Hikvision", articulos: 1112, fuentes: ["tarifa"] }).replace(/\s/g, " "), /^Hikvision · 1\.?112 artículos · Tarifa$/);
  assert.equal(resumenMarca({ marca: "Bosch", articulos: 0, fuentes: ["manual"] }), "Bosch · A mano");
});

test("variantes y mensajes", () => {
  assert.equal(variantesTexto({ "HIKVISION PRO": 529, "HIKVISION PRO NO CCTV": 297 }), "HIKVISION PRO (529) · HIKVISION PRO NO CCTV (297)");
  assert.equal(variantesTexto({}), "");
  assert.equal(variantesTexto(null), "");
  assert.match(mensajeMarcas(403), /solo Dirección/);
  assert.equal(mensajeMarcas(422, "Escribe el nombre de la marca"), "Escribe el nombre de la marca");
  assert.match(mensajeMarcas(500), /No se han podido leer/);
});
