import assert from "node:assert/strict";
import test from "node:test";
import { ayudaSinMicrofonos, elegir, mensajeError, mensajeTranscripcion, nivel, nombre, restricciones, soloEntradas } from "../lib/microfonos.js";

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

test("al transcribir se distingue «no se oye nada» de «el servicio de voz no funciona»", () => {
  assert.equal(mensajeTranscripcion(200, "hola"), "");
  assert.match(mensajeTranscripcion(200, "  "), /No he oído palabras/);
  assert.match(mensajeTranscripcion(500), /servicio de voz.*error 500/);
  assert.match(mensajeTranscripcion(503), /docker compose logs voz/);
  assert.match(mensajeTranscripcion(0), /no responde\./);
  assert.match(mensajeTranscripcion(401), /sesión ha caducado/);
});

test("sin micrófonos a la vista se explica por qué", () => {
  assert.match(ayudaSinMicrofonos(false, true), /localhost:3000/);
  assert.match(ayudaSinMicrofonos(true, false), /localhost:3000/);
  assert.match(ayudaSinMicrofonos(true, true), /Detectar micrófonos/);
});
