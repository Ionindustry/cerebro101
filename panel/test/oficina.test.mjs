// node --test panel/test
import assert from "node:assert/strict";
import test from "node:test";
import { COLUMNAS, SALA, COLOR, crearEscena, estadoDemo, iso } from "../lib/oficina.js";

const dep = (id, n, conDirector = true) => ({ id, nombre: id.toUpperCase(),
  agentes: Array.from({ length: n }, (_, i) => ({ id: `${id}-${i}`, director: conDirector && i === 0 })) });
const REAL = [["direccion", 8], ["finanzas", 6], ["comercial", 11], ["marketing", 10], ["atencion", 4], ["operaciones", 15], ["personas", 5], ["legal", 12],
  ["tecnologia", 4], ["conocimiento", 3], ["licitaciones", 12], ["telecom", 10], ["areas", 14]].map(([i, n]) => dep(i, n));

test("todos los agentes de la oficina real tienen puesto, sin repetir", () => {
  const e = crearEscena(REAL);
  const agentes = e.objetos.filter((o) => o.tipo === "agente");
  assert.equal(agentes.length, 114);
  assert.equal(new Set(agentes.map((a) => a.id)).size, 114);
  assert.equal(new Set(agentes.map((a) => `${a.cx},${a.cy}`)).size, 114, "dos agentes en el mismo sitio");
  assert.equal(e.salas.length, 13);
});

test("cada agente tiene su mesa con pantalla", () => {
  const e = crearEscena(REAL);
  const pantallas = new Set(e.objetos.filter((o) => o.tipo === "pantalla").map((o) => o.agente));
  assert.equal(pantallas.size, 114);
});

test("el director es el primero de su sala", () => {
  const e = crearEscena([dep("a", 5)]);
  const ag = e.objetos.filter((o) => o.tipo === "agente");
  const director = ag.find((a) => a.director);
  assert.equal(ag.filter((a) => a.director).length, 1);
  // el puesto 0 es el de menor profundidad (más al fondo) de la sala
  assert.equal(director.profundidad, Math.min(...ag.map((a) => a.profundidad)));
});

test("el orden de dibujo va de lo lejano a lo cercano", () => {
  const e = crearEscena(REAL);
  for (let i = 1; i < e.objetos.length; i++) assert.ok(e.objetos[i].profundidad >= e.objetos[i - 1].profundidad);
});

test("todo cabe en el encuadre", () => {
  const e = crearEscena(REAL);
  const [x, y, w, h] = e.viewBox;
  for (const o of e.objetos.filter((o) => o.tipo === "agente")) {
    assert.ok(o.cx > x && o.cx < x + w && o.cy - 40 > y && o.cy < y + h, o.id);
  }
  for (const s of e.salas) {
    assert.ok(s.etiqueta.x - 60 > x && s.etiqueta.x + 60 < x + w && s.etiqueta.y + 10 < y + h, s.id);
    assert.ok(s.caja[2] > 0 && s.caja[3] > 0);
  }
});

test("las salas no se solapan y las salas vacías son jardines", () => {
  const e = crearEscena(REAL);
  assert.equal(new Set(e.salas.map((s) => `${s.ox},${s.oy}`)).size, 13);
  assert.ok(e.objetos.some((o) => o.tipo === "arbol"));
  const solo = crearEscena([]);
  assert.equal(solo.salas.length, 0);
  assert.equal(solo.objetos.filter((o) => o.tipo === "agente").length, 0);
});

test("una sala con más de 16 agentes no desborda su cuadrícula", () => {
  const e = crearEscena([dep("grande", 20)]);
  assert.equal(e.objetos.filter((o) => o.tipo === "agente").length, 16);
});

test("la proyección isométrica es la esperada", () => {
  const [x, y] = iso(0, 0, 0);
  assert.deepEqual([x, y], [0, 0]);
  const [a] = iso(1, 0), [b] = iso(0, 1);
  assert.ok(a > 0 && b < 0, "x va hacia la derecha e y hacia la izquierda");
  assert.ok(iso(0, 0, 1)[1] < 0, "z sube");
  assert.ok(COLUMNAS * SALA > 0 && COLOR.senal.startsWith("#"));
});

test("la demostración da estados variados y estables para el mismo instante", () => {
  const a = estadoDemo(REAL, 3), b = estadoDemo(REAL, 3);
  assert.deepEqual(a, b);
  const estados = new Set(Object.values(a).map((v) => v.estado));
  assert.deepEqual([...estados].sort(), ["esperando", "reposo", "trabajando"]);
  assert.notDeepEqual(estadoDemo(REAL, 3), estadoDemo(REAL, 4));
});
