import assert from "node:assert/strict";
import test from "node:test";
import { barrasPorDia, contarPorDepartamento, esperaTexto, filtrarPorDepartamento, nombreDepartamento, repartoPorDepartamento } from "../lib/aprobaciones.js";

const lista = [{ id: 1, departamento: "finanzas" }, { id: 2, departamento: "comercial" }, { id: 3, departamento: "finanzas" }];

test("se cuentan y se filtran las solicitudes por departamento", () => {
  assert.deepEqual(contarPorDepartamento(lista), [{ id: "finanzas", n: 2 }, { id: "comercial", n: 1 }]);
  assert.deepEqual(contarPorDepartamento([]), []);
  assert.equal(filtrarPorDepartamento(lista, "finanzas").length, 2);
  assert.equal(filtrarPorDepartamento(lista, "").length, 3);
  assert.equal(filtrarPorDepartamento(lista, "legal").length, 0);
});

test("el nombre del departamento cae al id si no se conoce", () => {
  assert.equal(nombreDepartamento({ finanzas: { nombre: "Finanzas y Contabilidad" } }, "finanzas"), "Finanzas y Contabilidad");
  assert.equal(nombreDepartamento({}, "legal"), "legal");
});

test("la espera se dice en horas o en días", () => {
  assert.equal(esperaTexto(null), "—");
  assert.equal(esperaTexto(0.3), "menos de 1 h");
  assert.equal(esperaTexto(5.4), "5 h");
  assert.equal(esperaTexto(47), "47 h");
  assert.equal(esperaTexto(72), "3 días");
});

test("el reparto por departamento ordena por pendientes y da el máximo para las barras", () => {
  const resumen = { pendientes: { por_departamento: { finanzas: 2, comercial: 1 } },
    resueltas: { por_departamento: { finanzas: { aprobadas: 3, rechazadas: 0 }, legal: { aprobadas: 0, rechazadas: 4 } } } };
  const { filas, max } = repartoPorDepartamento(resumen, { finanzas: { nombre: "Finanzas" } });
  assert.deepEqual(filas.map((f) => [f.nombre, f.pendientes, f.aprobadas, f.rechazadas, f.total]),
    [["Finanzas", 2, 3, 0, 5], ["comercial", 1, 0, 0, 1], ["legal", 0, 0, 4, 4]]);
  assert.equal(max, 5);
  assert.deepEqual(repartoPorDepartamento(null), { filas: [], max: 1 });
});

test("las barras por día se escalan al día con más movimiento", () => {
  const b = barrasPorDia([{ dia: "a", creadas: 2, aprobadas: 1, rechazadas: 0 }, { dia: "b", creadas: 4, aprobadas: 2, rechazadas: 2 }, { dia: "c", creadas: 0, aprobadas: 0, rechazadas: 0 }]);
  assert.deepEqual(b.map((x) => [x.hCreadas, x.hAprobadas, x.hRechazadas]), [[50, 25, 0], [100, 50, 50], [0, 0, 0]]);
  assert.deepEqual(barrasPorDia([{ dia: "a", creadas: 0, aprobadas: 0, rechazadas: 0 }])[0].hCreadas, 0);
});
