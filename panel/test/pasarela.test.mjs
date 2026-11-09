import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { enviar, mensajeFallo, reenviarSeguro } from "../lib/pasarela.js";

function servidor(manejador) {
  return new Promise((ok) => { const s = http.createServer(manejador); s.listen(0, "127.0.0.1", () => ok({ s, url: `http://127.0.0.1:${s.address().port}` })); });
}

test("reenvía método, cuerpo y devuelve estado y texto", async () => {
  const { s, url } = await servidor((req, res) => { let b = ""; req.on("data", (t) => (b += t)); req.on("end", () => { res.statusCode = 201; res.end(JSON.stringify({ metodo: req.method, b })); }); });
  const r = await enviar(`${url}/x`, { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"a":1}' });
  s.close();
  assert.equal(r.status, 201);
  assert.deepEqual(JSON.parse(r.texto), { metodo: "POST", b: '{"a":1}' });
});

test("espera una respuesta lenta (más de lo que tardaría un corte corto)", async () => {
  const { s, url } = await servidor((req, res) => setTimeout(() => res.end("{}"), 300));
  const r = await enviar(url, { plazoMs: 5000 });
  s.close();
  assert.equal(r.status, 200);
});

test("pasado el plazo da 504 con un mensaje claro y JSON válido", async () => {
  const { s, url } = await servidor(() => {});
  const r = await reenviarSeguro(url, { plazoMs: 100 });
  s.closeAllConnections?.(); s.close();
  assert.equal(r.status, 504);
  const d = JSON.parse(r.texto);
  assert.equal(d.codigo, "pasarela");
  assert.match(d.detail, /no ha respondido/);
});

test("si la API no está, da 502 con mensaje claro", async () => {
  const { s, url } = await servidor(() => {});
  s.close();
  await new Promise((r) => setTimeout(r, 50));
  const r = await reenviarSeguro(url, { plazoMs: 2000 });
  assert.equal(r.status, 502);
  assert.match(JSON.parse(r.texto).detail, /No se puede conectar/);
});

test("mensajeFallo: conexión cortada y error desconocido", () => {
  assert.match(mensajeFallo({ code: "ECONNRESET" }), /cortó la conexión/);
  assert.match(mensajeFallo(new Error("x")), /Falló la comunicación/);
});
