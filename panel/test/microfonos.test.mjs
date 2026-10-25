import assert from "node:assert/strict";
import test from "node:test";
import { elegir, mensajeError, nivel, nombre, restricciones, soloEntradas } from "../lib/microfonos.js";

const disp = [
  { kind: "audioinput", deviceId: "default", label: "Predeterminado" },
  { kind: "audioinput", deviceId: "communications", label: "Comunicaciones" },
  { kind: "audioinput", deviceId: "cam1", label: "Webcam C920" },
  { kind: "videoinput", deviceId: "v1", label: "Cámara" },
  { kind: "audiooutput", deviceId: "o1", label: "Altavoces" },
];

test("solo salen las entradas de audio, sin el duplicado de «comunicaciones»", () => {
  assert.deepEqual(soloEntradas(disp).map((d) => d.deviceId), ["default", "cam1"]);
  assert.deepEqual(soloEntradas(undefined), []);
});

test("sin etiqueta (sin permiso) se numeran", () => {
  assert.equal(nombre({ label: "" }, 1), "Micrófono 2");
  assert.equal(nombre({ label: "Webcam C920" }, 0), "Webcam C920");
});

test("se mantiene la elección guardada si sigue conectada; si no, el predeterminado", () => {
  assert.equal(elegir(disp, "cam1"), "cam1");
  assert.equal(elegir(disp, "desenchufado"), "default");
  assert.equal(elegir(disp, ""), "default");
  assert.equal(elegir([{ kind: "audioinput", deviceId: "x" }], null), "x");
  assert.equal(elegir([], "cam1"), "");
});

test("a un micrófono concreto se le exige; el predeterminado no", () => {
  assert.deepEqual(restricciones("cam1"), { audio: { deviceId: { exact: "cam1" } } });
  assert.deepEqual(restricciones("default"), { audio: true });
  assert.deepEqual(restricciones(""), { audio: true });
});

test("los errores del navegador se explican en claro", () => {
  assert.match(mensajeError({ name: "NotAllowedError" }), /candado/);
  assert.match(mensajeError({ name: "NotFoundError" }), /cámara está conectada/);
  assert.match(mensajeError({ name: "NotReadableError" }), /Otro programa/);
  assert.match(mensajeError(new Error("raro")), /No se ha podido/);
});

test("el nivel va de 0 (silencio) a 1 (fuerte)", () => {
  assert.equal(nivel([128, 128, 128]), 0);
  assert.equal(nivel([128, 192, 64]), 1);
  assert.ok(nivel([128, 144]) > 0 && nivel([128, 144]) < 1);
  assert.equal(nivel([]), 0);
});
