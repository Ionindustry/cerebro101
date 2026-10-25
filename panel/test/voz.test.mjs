import assert from "node:assert/strict";
import test from "node:test";
import { detectarIdioma, limpiarParaHablar, mensajeErrorVoz, recortarParaHablar } from "../lib/voz.js";

test("se quitan las marcas de formato, los enlaces y el código antes de leer", () => {
  assert.equal(limpiarParaHablar("## Resumen\n- **Ventas** subieron\n- *Costes* bajaron"), "Resumen. Ventas subieron. Costes bajaron");
  assert.equal(limpiarParaHablar("Mira [la guía](https://aepd.es/x) y https://otra.com/a"), "Mira la guía y");
  assert.equal(limpiarParaHablar("Usa `docker ps`.\n```\nsecreto()\n```\nListo"), "Usa docker ps. Listo");
  assert.equal(limpiarParaHablar(""), "");
  assert.equal(limpiarParaHablar(undefined), "");
});

test("una respuesta larga se corta al final de una frase", () => {
  const largo = "Primera frase corta. ".repeat(100);
  const r = recortarParaHablar(largo, 200);
  assert.ok(r.length <= 200);
  assert.ok(r.endsWith("."));
  assert.equal(recortarParaHablar("corto", 200), "corto");
  assert.equal(recortarParaHablar("x".repeat(500), 100).length, 100);
});

test("el catalán se reconoce y el castellano es lo normal", () => {
  assert.equal(detectarIdioma("Bon dia, això és molt important per a nosaltres"), "ca");
  assert.equal(detectarIdioma("Buenos días, esto es muy importante para nosotros"), "es");
  assert.equal(detectarIdioma("Hola"), "es");
  assert.equal(detectarIdioma(""), "es");
});

test("los fallos de la voz se explican", () => {
  assert.match(mensajeErrorVoz(503), /voces_descargar/);
  assert.equal(mensajeErrorVoz(503, "Falta la voz X"), "Falta la voz X");
  assert.match(mensajeErrorVoz(0), /No he podido contactar/);
  assert.match(mensajeErrorVoz(500), /error 500/);
  assert.match(mensajeErrorVoz(401), /sesión ha caducado/);
});
