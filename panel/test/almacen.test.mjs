// node --test panel/test   (con REDIS_PANEL_URL=redis://:clave@host:6379 prueba también contra un Redis real)
import assert from "node:assert/strict";
import test from "node:test";

process.env.PANEL_SESION_SECRET = "clave-de-prueba";
const { cifrar, descifrar, guardarSesion, leerSesion, borrarSesion, tomarTurno, soltarTurno, ordenRedis, conRedis } = await import("../lib/almacen.js");

test("el cifrado es reversible y no deja el contenido a la vista", () => {
  const s = { acceso: "token-secreto", usuario: "ana" };
  const c = cifrar(s);
  assert.ok(!c.includes("token-secreto") && !Buffer.from(c, "base64url").toString("latin1").includes("ana"));
  assert.deepEqual(descifrar(c), s);
});

test("un valor manipulado o cifrado con otra clave no se acepta", () => {
  const c = cifrar({ a: 1 });
  const b = Buffer.from(c, "base64url"); b[b.length - 1] ^= 1;
  assert.throws(() => descifrar(b.toString("base64url")));
  process.env.PANEL_SESION_SECRET = "otra";
  assert.throws(() => descifrar(c));
  process.env.PANEL_SESION_SECRET = "clave-de-prueba";
});

test("sin Redis, las sesiones van a memoria", async (t) => {
  if (conRedis()) return t.skip("hay Redis configurado");
  await guardarSesion("id1", { usuario: "ana" }, 60);
  assert.equal((await leerSesion("id1")).usuario, "ana");
  await borrarSesion("id1");
  assert.equal(await leerSesion("id1"), null);
});

test("con Redis: guardar, leer, caducar, borrar y turno", async (t) => {
  if (!conRedis()) return t.skip("define REDIS_PANEL_URL para probar contra un Redis real");
  await guardarSesion("idR", { usuario: "ana", acceso: "tok" }, 60);
  assert.equal((await leerSesion("idR")).acceso, "tok");
  const crudo = await ordenRedis(process.env.REDIS_PANEL_URL, ["KEYS", "sesion:*"]).catch(() => null);
  assert.ok(crudo === null || !String(crudo).includes("idR"), "la cookie no aparece en claro como clave");
  assert.ok((await ordenRedis(process.env.REDIS_PANEL_URL, ["TTL", "sesion:" + (await import("node:crypto")).createHash("sha256").update("idR").digest("hex")])) > 0);
  assert.equal(await tomarTurno("idR"), true);
  assert.equal(await tomarTurno("idR"), false, "solo uno renueva a la vez");
  await soltarTurno("idR");
  assert.equal(await tomarTurno("idR"), true);
  await soltarTurno("idR");
  await borrarSesion("idR");
  assert.equal(await leerSesion("idR"), null);
  await guardarSesion("corta", { x: 1 }, 1);
  await new Promise((r) => setTimeout(r, 1300));
  assert.equal(await leerSesion("corta"), null, "caduca sola");
  await guardarSesion("grande", { x: "ñ".repeat(20000) }, 60);        // respuestas largas y caracteres no ASCII
  assert.equal((await leerSesion("grande")).x.length, 20000);
  await borrarSesion("grande");
});
