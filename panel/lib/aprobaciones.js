// Ayudas del panel de Aprobaciones (dashboard y clasificación por departamentos). Sin dependencias: se prueba con node --test.

export const nombreDepartamento = (deps = {}, id) => deps[id]?.nombre || id;

// Cuántas solicitudes hay de cada departamento: [{ id, n }], de más a menos y luego por nombre
export function contarPorDepartamento(lista = []) {
  const m = {};
  for (const s of lista) m[s.departamento] = (m[s.departamento] || 0) + 1;
  return Object.entries(m).map(([id, n]) => ({ id, n })).sort((a, b) => b.n - a.n || a.id.localeCompare(b.id));
}

export const filtrarPorDepartamento = (lista = [], dep = "") => (dep ? lista.filter((s) => s.departamento === dep) : lista);

// «hace 3 h», «hace 2 días»: lo que lleva esperando una firma
export function esperaTexto(horas) {
  if (horas === null || horas === undefined) return "—";
  if (horas < 1) return "menos de 1 h";
  if (horas < 48) return `${Math.round(horas)} h`;
  return `${Math.round(horas / 24)} días`;
}

// Filas del reparto por departamento para el dashboard: pendientes, aprobadas y rechazadas de cada uno, con el máximo para dibujar las barras
export function repartoPorDepartamento(resumen, deps = {}) {
  if (!resumen) return { filas: [], max: 1 };
  const ids = new Set([...Object.keys(resumen.pendientes.por_departamento), ...Object.keys(resumen.resueltas.por_departamento)]);
  const filas = [...ids].map((id) => {
    const r = resumen.resueltas.por_departamento[id] || { aprobadas: 0, rechazadas: 0 };
    const p = resumen.pendientes.por_departamento[id] || 0;
    return { id, nombre: nombreDepartamento(deps, id), pendientes: p, aprobadas: r.aprobadas, rechazadas: r.rechazadas, total: p + r.aprobadas + r.rechazadas };
  }).sort((a, b) => b.pendientes - a.pendientes || b.total - a.total || a.nombre.localeCompare(b.nombre));
  return { filas, max: Math.max(1, ...filas.map((f) => f.total)) };
}

// Barras de la serie por día (altura 0–100 sobre el máximo de creadas/decididas)
export function barrasPorDia(serie = [], alto = 100) {
  const max = Math.max(1, ...serie.map((d) => Math.max(d.creadas, d.aprobadas + d.rechazadas)));
  return serie.map((d) => ({ ...d, hCreadas: (d.creadas / max) * alto, hAprobadas: (d.aprobadas / max) * alto, hRechazadas: (d.rechazadas / max) * alto }));
}
