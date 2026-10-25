import assert from "node:assert/strict";
import test from "node:test";
import { mensajeError, puedeCambiar, resumen, uso } from "../lib/modelosExternos.js";

const claude = { id: "claude", nombre: "Claude (Anthropic)", estado: "conectado", activo: true, tiene_clave: true, usadas_hoy: 3, limite_diario: 200 };
const gpt = { id: "chatgpt", nombre: "ChatGPT (OpenAI)", estado: "sin_clave", activo: false, tiene_clave: false, usadas_hoy: 0, limite_diario: 200 };

test("el resumen dice qué modelos están conectados", () => {
  assert.equal(resumen([claude, gpt]), "Claude conectado");
  assert.equal(resumen([claude, { ...gpt, estado: "conectado" }]), "Claude y ChatGPT conectados");
  assert.equal(resumen([{ ...claude, estado: "desconectado" }, gpt]), "todo en local");
  assert.equal(resumen([]), "todo en local");
});

test("el uso de hoy se muestra o se avisa de que no está disponible", () => {
  assert.equal(uso(claude), "3 de 200 consultas hoy");
  assert.match(uso({ ...claude, usadas_hoy: null }), /no disponible/);
});

test("sin clave no se puede conectar, pero conectado siempre se puede desconectar", () => {
  assert.equal(puedeCambiar(gpt), false);
  assert.equal(puedeCambiar(claude), true);
  assert.equal(puedeCambiar({ ...gpt, tiene_clave: true }), true);
  assert.equal(puedeCambiar({ ...gpt, activo: true }), true);
});

test("los errores se explican en claro", () => {
  assert.match(mensajeError(403), /Dirección/);
  assert.equal(mensajeError(409, "Falta la clave de claude"), "Falta la clave de claude");
  assert.match(mensajeError(503), /Inténtalo/);
  assert.match(mensajeError(500), /No se ha podido/);
});
