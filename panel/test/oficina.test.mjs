// node --test panel/test
import assert from "node:assert/strict";
import test from "node:test";
import { COLUMNAS, HUECO, PUESTOS, SALA, distribucion, estadoDemo, puesto } from "../lib/oficina.js";

const dep = (id, n, conDirector = true) => ({ id, nombre: id.toUpperCase(),
  agentes: Array.from({ length: n }, (_, i) => ({ id: `${id}-${i}`, director: conDirector && i === n - 1 })) });
const REAL = [["direccion", 8], ["finanzas", 6], ["comercial", 11], ["marketing", 10], ["atencion", 4], ["operaciones", 15], ["personas", 5], ["legal", 12],
  ["tecnologia", 4], ["conocimiento", 3], ["licitaciones", 12], ["telecom", 10], ["areas", 14]].map(([i, n]) => dep(i, n));

test("todos los agentes de la oficina real tienen puesto, sin repetir", () => {
  const d = distribucion(REAL);
  assert.equal(d.agentes.length, 114);
  assert.equal(new Set(d.agentes.map((a) => a.id)).size, 114);
  assert.equal(new Set(d.agentes.map((a) => `${a.pos.x.toFixed(2)},${a.pos.z.toFixed(2)}`)).size, 114, "dos agentes en el mismo sitio");
  assert.equal(new Set(d.agentes.map((a) => `${a.mesa.x.toFixed(2)},${a.mesa.z.toFixed(2)}`)).size, 114, "dos mesas en el mismo sitio");
  assert.equal(d.salas.length, 13);
  assert.equal(d.jardines.length, COLUMNAS * COLUMNAS - 13);
});

test("cada agente queda dentro de su sala", () => {
  const d = distribucion(REAL);
  for (const a of d.agentes) {
    const s = d.salas.find((x) => x.id === a.sala);
    assert.ok(a.pos.x > s.x && a.pos.x < s.x + SALA && a.pos.z > s.z && a.pos.z < s.z + SALA, a.id);
    assert.ok(a.mesa.x > s.x && a.mesa.x + 1.3 < s.x + SALA, `la mesa de ${a.id} se sale de la sala`);
  }
});

test("el agente está delante de su mesa, centrado, donde iría la silla", () => {
  for (const a of distribucion(REAL).agentes) {
    assert.ok(Math.abs(a.pos.x - (a.mesa.x + 0.65)) < 1e-9, "centrado con la mesa");
    assert.ok(a.pos.z - a.mesa.z > 0.8 && a.pos.z - a.mesa.z < 1.2, "delante de la mesa (fuera del tablero)");
  }
});

test("el director ocupa el puesto 0", () => {
  const d = distribucion([dep("a", 5)]);
  const dir = d.agentes.find((a) => a.director);
  assert.equal(dir.puesto, 0);
  assert.equal(d.agentes.filter((a) => a.director).length, 1);
});

test("las salas no se solapan", () => {
  const d = distribucion(REAL);
  assert.equal(new Set(d.salas.map((s) => `${s.x},${s.z}`)).size, 13);
  for (const a of d.salas) for (const b of d.salas) if (a !== b) {
    assert.ok(Math.abs(a.x - b.x) >= SALA + HUECO - 1e-9 || Math.abs(a.z - b.z) >= SALA + HUECO - 1e-9);
  }
});

test("una sala con más de 16 agentes no desborda su cuadrícula; sin departamentos todo son jardines", () => {
  assert.equal(distribucion([dep("grande", 20)]).agentes.length, PUESTOS * PUESTOS);
  const v = distribucion([]);
  assert.equal(v.salas.length, 0);
  assert.equal(v.jardines.length, 16);
});

test("la cuadrícula de puestos cabe en la sala", () => {
  for (let k = 0; k < PUESTOS * PUESTOS; k++) {
    const p = puesto(k);
    assert.ok(p.x + 1.3 < SALA && p.z + 1.0 + 0.2 < SALA);
  }
});

test("el centro de la oficina es el de su cuadrícula", () => {
  const d = distribucion(REAL);
  assert.equal(d.ancho, COLUMNAS * SALA + (COLUMNAS - 1) * HUECO);
  assert.ok(Math.abs(d.centro.x - d.ancho / 2) < 1e-9);
});

test("la demostración da estados variados y estables para el mismo instante", () => {
  const a = estadoDemo(REAL, 3), b = estadoDemo(REAL, 3);
  assert.deepEqual(a, b);
  assert.deepEqual([...new Set(Object.values(a).map((v) => v.estado))].sort(), ["esperando", "reposo", "trabajando"]);
  assert.notDeepEqual(estadoDemo(REAL, 3), estadoDemo(REAL, 4));
});
