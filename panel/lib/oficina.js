// Distribución de la oficina (sin gráficos: se prueba con node --test) y datos de demostración.
// Mundo en unidades (≈ metros): x hacia la derecha, z hacia el espectador, y hacia arriba. El agente está de pie donde iría la silla: delante de su mesa.

export const SALA = 8.6;                    // lado de cada sala
export const HUECO = 1.6;                   // pasillo entre salas
export const COLUMNAS = 4;
export const PUESTOS = 4;                   // cada sala tiene una cuadrícula de 4 × 4 puestos (16 agentes)

export const COLOR = {
  fondo: "#f1f1f3", suelo: "#e8e8eb", sala: "#f8f8f9", linea: "#1c1c1c", blanco: "#ffffff", mesa: "#fbfbfc", sombra: "#c9c9cf",
  tinta: "#0b0b0d", senal: "#f2584b", ambar: "#e0a21a", reposo: "#9a9aa2", arbol: "#d9d9de",
};

export const ESTADOS = {
  trabajando: { nombre: "Trabajando", color: COLOR.senal },
  esperando: { nombre: "Espera aprobación", color: "#c98a0b" },
  reposo: { nombre: "En reposo", color: COLOR.reposo },
};

export function origenSala(i) {
  const col = i % COLUMNAS, fila = Math.floor(i / COLUMNAS);
  return { x: col * (SALA + HUECO), z: fila * (SALA + HUECO) };
}

// Puesto k de una sala: posición de la mesa (esquina) respecto al origen de la sala. El 0 es el del fondo-izquierda (el del director).
export function puesto(k) {
  const col = k % PUESTOS, fila = Math.floor(k / PUESTOS);
  return { x: 0.9 + col * 1.85, z: 1.7 + fila * 1.66 };
}

export function distribucion(departamentos) {
  const total = Math.max(departamentos.length, COLUMNAS * COLUMNAS);
  const filas = Math.ceil(total / COLUMNAS);
  const ancho = COLUMNAS * SALA + (COLUMNAS - 1) * HUECO, fondo = filas * SALA + (filas - 1) * HUECO;
  const salas = [], jardines = [], agentes = [];
  for (let i = 0; i < total; i++) {
    const o = origenSala(i), dep = departamentos[i];
    if (!dep) { jardines.push({ ...o }); continue; }
    salas.push({ id: dep.id, nombre: dep.nombre, ...o, centro: { x: o.x + SALA / 2, z: o.z + SALA / 2 }, n: dep.agentes.length });
    [...dep.agentes].sort((a, b) => (b.director ? 1 : 0) - (a.director ? 1 : 0)).slice(0, PUESTOS * PUESTOS).forEach((a, k) => {
      const p = puesto(k);
      agentes.push({ id: a.id, sala: dep.id, director: !!a.director, mesa: { x: o.x + p.x, z: o.z + p.z }, pos: { x: o.x + p.x + 0.65, z: o.z + p.z + 1.0 }, puesto: k });
    });
  }
  return { ancho, fondo, centro: { x: ancho / 2, z: fondo / 2 }, salas, jardines, agentes };
}

export function estadoDemo(departamentos, tick) {
  // Estados de ejemplo, marcados como demostración en la pantalla (no son datos reales)
  const mapa = {};
  let n = 0;
  for (const d of departamentos) for (const a of d.agentes) {
    const v = (n * 7 + tick) % 11;
    mapa[a.id] = { estado: v < 3 ? "trabajando" : v === 3 ? "esperando" : "reposo",
                   detalle: v < 3 ? ["Revisando el correo de RR.HH.", "Preparando un presupuesto", "Leyendo una factura (OCR)", "Consultando el ERP"][(n + tick) % 4] : v === 3 ? "Espera una aprobación" : null };
    n++;
  }
  return mapa;
}
