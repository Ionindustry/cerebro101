import test from "node:test";
import assert from "node:assert/strict";
import { cotizacionAEnvio, mailtoHref, mensajeCotizaciones, referenciaDeProducto, respuestaAEnvio, respuestaTexto, resumenCotizacion } from "../lib/cotizaciones.js";

const form = { referencia: " DS-2CD2143G2-I ", cantidad: "12", plazo_tipo: "dias", plazo_valor: "15", proveedor: "A-Secur", modo: "manual", marca: "Hikvision", licitacion: "ab54b97a-5012-4a4c-92dc-b4d99908f0fd", partida: "7" };

test("nueva cotización: del formulario al cuerpo, o un mensaje claro", () => {
  assert.deepEqual(cotizacionAEnvio(form).cuerpo, { referencia: "DS-2CD2143G2-I", cantidad: 12, plazo_tipo: "dias", plazo_valor: 15, proveedor: "A-Secur", modo: "manual", marca: "Hikvision", licitacion: form.licitacion, partida: 7 });
  assert.deepEqual(cotizacionAEnvio({ ...form, plazo_tipo: "fecha", plazo_valor: "2026-12-10" }).cuerpo.plazo_valor, "2026-12-10");
  for (const [k, v] of [["referencia", " "], ["cantidad", "0"], ["cantidad", "x"], ["plazo_valor", "0"], ["proveedor", ""], ["modo", ""], ["modo", "otro"]]) assert.ok(cotizacionAEnvio({ ...form, [k]: v }).error, `${k}=${v}`);
  assert.ok(cotizacionAEnvio({ ...form, plazo_tipo: "fecha", plazo_valor: "mañana" }).error);
});

test("respuesta del proveedor: precio con coma, moneda y plazos", () => {
  assert.deepEqual(respuestaAEnvio({ precio: "12,5", moneda: "USD", plazo_dias: "7", validez_hasta: "2026-12-31", nota: " ok " }).cuerpo, { precio: "12.5", moneda: "USD", nota: "ok", plazo_dias: 7, validez_hasta: "2026-12-31" });
  assert.equal(respuestaAEnvio({ precio: "5", moneda: "JPY" }).cuerpo.moneda, "EUR");
  for (const malo of [{ precio: "" }, { precio: "0" }, { precio: "-1" }, { precio: "abc" }, { precio: "1.00001" }, { precio: "5", plazo_dias: "x" }, { precio: "5", plazo_dias: "9999" }, { precio: "5", validez_hasta: "pronto" }]) assert.ok(respuestaAEnvio(malo).error, JSON.stringify(malo));
});

test("textos y el enlace mailto con solo lo que ya lleva el correo", () => {
  assert.equal(resumenCotizacion({ referencia: "R-1", cantidad: 3, proveedor: "A-Secur", plazo: "15 días" }), "R-1 × 3 · A-Secur · plazo 15 días");
  assert.match(respuestaTexto({ precio: "12.5", moneda: "EUR", plazo_dias: 7, validez_hasta: "2026-12-31" }).replace(/\s/g, " "), /^12,5 EUR · entrega en 7 días · válida hasta 2026-12-31$/);
  assert.equal(respuestaTexto({}), "");
  const h = mailtoHref({ email: "ventas@a-secur.com", asunto: "Solicitud · R-1", cuerpo: "Línea 1\nLínea 2" });
  assert.equal(h, "mailto:ventas@a-secur.com?subject=Solicitud%20%C2%B7%20R-1&body=L%C3%ADnea%201%0ALínea%202".replace("L%C3%ADnea%201%0ALínea%202", "L%C3%ADnea%201%0AL%C3%ADnea%202"));
  assert.match(mensajeCotizaciones(403), /Dirección y Licitaciones/);
  assert.equal(mensajeCotizaciones(422, "Elige el proveedor"), "Elige el proveedor");
});

test("la referencia que se pide sale del texto del producto", () => {
  assert.equal(referenciaDeProducto("Cámara domo Milesight MS-C8573-FPB 4MP"), "MS-C8573-FPB");
  assert.equal(referenciaDeProducto("Hikvision DS-2CD2143G2-I (4 MP)"), "DS-2CD2143G2-I");
  assert.equal(referenciaDeProducto("Grabador de vídeo en red"), "Grabador de vídeo en red");              // sin referencia: el texto recortado
  assert.equal(referenciaDeProducto(""), "");
  assert.ok(referenciaDeProducto("x".repeat(200)).length <= 80);
});
