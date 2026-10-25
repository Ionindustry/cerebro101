// Geometría de la oficina isométrica (sin React: se prueba con node --test).
// Mundo: x crece hacia abajo-derecha de la pantalla, y hacia abajo-izquierda, z hacia arriba. Lo más cercano al espectador es lo de mayor x+y.

export const ESCALA = 17;                    // píxeles por unidad de mundo
const C = Math.cos(Math.PI / 6);
export const SALA = 8.4;                     // lado de cada sala
export const HUECO = 1.3;                    // pasillo entre salas
export const COLUMNAS = 4;
const ALTO_MURO = 1.15;
const PUESTOS = 4;                           // cada sala tiene una cuadrícula de 4 × 4 puestos (16 agentes)

export const iso = (x, y, z = 0) => [(x - y) * C * ESCALA, (x + y) * 0.5 * ESCALA - z * ESCALA];
const pts = (lista) => lista.map(([x, y, z]) => iso(x, y, z).map((n) => +n.toFixed(1)).join(",")).join(" ");

export const COLOR = {
  suelo: "#ececee", sala: "#f8f8f9", salaLinea: "#1c1c1c", murosCara: "#ffffff", murosIzq: "#dedee2", murosDer: "#cbcbd1",
  mesaTapa: "#ffffff", mesaIzq: "#e3e3e7", mesaDer: "#cfcfd5", pantalla: "#2a2a2e", tinta: "#0d0d0f", senal: "#f2584b",
  arbol: "#d6d6da", arbolClaro: "#ebebee",
};

// Un prisma con sus tres caras visibles (arriba, la que mira abajo-izquierda —y+d— y la que mira abajo-derecha —x+w—).
export function caja(x, y, z, w, d, h, c = { tapa: COLOR.mesaTapa, izq: COLOR.mesaIzq, der: COLOR.mesaDer }, extra = {}) {
  return [
    { tipo: "poli", puntos: pts([[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z + h], [x, y + d, z + h]]), relleno: c.izq, ...extra },
    { tipo: "poli", puntos: pts([[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z + h], [x + w, y, z + h]]), relleno: c.der, ...extra },
    { tipo: "poli", puntos: pts([[x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h]]), relleno: c.tapa, ...extra },
  ];
}

export function origenSala(i) {
  const col = i % COLUMNAS, fila = Math.floor(i / COLUMNAS);
  return [col * (SALA + HUECO), fila * (SALA + HUECO)];
}

// Puestos de una sala: cuadrícula 4 × 4. La mesa ocupa (1.15 × 0.6); el agente se coloca a su lado.
export function puesto(k) {
  const col = k % PUESTOS, fila = Math.floor(k / PUESTOS);
  return { mx: 1.0 + col * 1.9, my: 1.55 + fila * 1.62 };
}

export function crearEscena(departamentos) {
  const suelos = [], objetos = [];
  const total = Math.max(departamentos.length, COLUMNAS * COLUMNAS);
  const filas = Math.ceil(total / COLUMNAS);
  const ancho = COLUMNAS * SALA + (COLUMNAS - 1) * HUECO, fondo = filas * SALA + (filas - 1) * HUECO;
  const margen = 2.6;
  suelos.push({ tipo: "poli", puntos: pts([[-margen, -margen, 0], [ancho + margen, -margen, 0], [ancho + margen, fondo + margen, 0], [-margen, fondo + margen, 0]]),
                relleno: COLOR.suelo, id: "suelo" });
  // grosor del suelo (como la losa del render)
  suelos.push({ tipo: "poli", puntos: pts([[-margen, fondo + margen, 0], [ancho + margen, fondo + margen, 0], [ancho + margen, fondo + margen, -0.5], [-margen, fondo + margen, -0.5]]), relleno: "#d9d9dd" });
  suelos.push({ tipo: "poli", puntos: pts([[ancho + margen, -margen, 0], [ancho + margen, fondo + margen, 0], [ancho + margen, fondo + margen, -0.5], [ancho + margen, -margen, -0.5]]), relleno: "#c8c8ce" });

  const salas = [], puestos = [];
  for (let i = 0; i < total; i++) {
    const [ox, oy] = origenSala(i);
    const dep = departamentos[i];
    if (!dep) {                                         // hueco sin departamento: jardín con árboles
      for (const [dx, dy, r] of [[2.0, 2.2, 1.0], [5.6, 1.8, 1.25], [3.6, 5.4, 1.1], [6.6, 6.2, 0.85], [1.4, 6.4, 0.8]]) {
        objetos.push({ tipo: "arbol", profundidad: ox + dx + oy + dy, ...arbol(ox + dx, oy + dy, r) });
      }
      continue;
    }
    salas.push({ id: dep.id, nombre: dep.nombre, ox, oy });
    suelos.push({ tipo: "poli", puntos: pts([[ox, oy, 0], [ox + SALA, oy, 0], [ox + SALA, oy + SALA, 0], [ox, oy + SALA, 0]]), relleno: COLOR.sala,
                  linea: COLOR.salaLinea, sala: dep.id, id: `sala-${dep.id}` });
    // muros bajos al fondo (los dos lados que dan al espectador no existen: se ve el interior), con un hueco de puerta
    const grosor = 0.22;
    objetos.push(...muro(ox, oy, SALA * 0.38, grosor, "x"), ...muro(ox + SALA * 0.52, oy, SALA * 0.48, grosor, "x"));
    objetos.push(...muro(ox, oy, grosor, SALA * 0.45, "y"), ...muro(ox, oy + SALA * 0.58, grosor, SALA * 0.42, "y"));
    // agentes: el director primero (puesto 0), luego el resto por orden
    const orden = [...dep.agentes].sort((a, b) => (b.director ? 1 : 0) - (a.director ? 1 : 0));
    orden.slice(0, PUESTOS * PUESTOS).forEach((ag, k) => {
      const p = puesto(k), mx = ox + p.mx, my = oy + p.my;
      objetos.push(...mesa(mx, my, ag.id).map((o) => ({ ...o, profundidad: mx + my + 0.55 })));
      const [ax, ay] = [mx + 1.45, my + 0.32];
      const [cx, cy] = iso(ax, ay, 0);
      objetos.push({ tipo: "agente", id: ag.id, departamento: dep.id, director: !!ag.director, cx: +cx.toFixed(1), cy: +cy.toFixed(1),
                     profundidad: ax + ay });
      puestos.push({ id: ag.id, sala: dep.id });
    });
    const [lx, ly] = iso(ox + SALA / 2, oy + SALA, 0);
    const esquinas = [iso(ox, oy, ALTO_MURO), iso(ox + SALA, oy, ALTO_MURO), iso(ox, oy + SALA, 0), iso(ox + SALA, oy + SALA, 0)];
    const ex = esquinas.map((p) => p[0]), ey = esquinas.map((p) => p[1]);
    Object.assign(salas[salas.length - 1], { etiqueta: { x: +lx.toFixed(1), y: +(ly + 15).toFixed(1) },
      caja: [Math.min(...ex), Math.min(...ey), Math.max(...ex) - Math.min(...ex), Math.max(...ey) - Math.min(...ey)].map((n) => +n.toFixed(1)) });
  }
  // árboles a lo largo de los bordes (fondo y laterales), como los del render
  for (let k = 0; k < 9; k++) objetos.push({ tipo: "arbol", profundidad: -margen + k * 4, ...arbol(-1.2, k * 4.4 + 1, 0.7) });
  objetos.sort((a, b) => a.profundidad - b.profundidad);

  const todos = [...suelos, ...objetos].flatMap((o) => o.puntos ? o.puntos.split(" ").map((p) => p.split(",").map(Number)) : [[o.cx ?? o.x, (o.cy ?? o.y) - 40], [o.cx ?? o.x, (o.cy ?? o.y) + 30]]);
  const xs = todos.map((p) => p[0]), ys = todos.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs) - 14, Math.max(...xs) + 14, Math.min(...ys) - 6, Math.max(...ys) + 26];
  return { suelos, objetos, salas, puestos, viewBox: [x0, y0, x1 - x0, y1 - y0].map((n) => Math.round(n)) };
}

function muro(x, y, w, d, eje) {
  const c = { tapa: COLOR.murosCara, izq: COLOR.murosIzq, der: COLOR.murosDer };
  return caja(x, y, 0, w, d, ALTO_MURO, c).map((o) => ({ ...o, profundidad: x + y + (eje === "x" ? w / 2 : d / 2) - 0.6 }));
}

function mesa(x, y, agente) {
  const c = { tapa: COLOR.mesaTapa, izq: COLOR.mesaIzq, der: COLOR.mesaDer };
  const [px, py] = iso(x + 0.5, y + 0.2, 0.95);
  return [...caja(x, y, 0, 1.15, 0.6, 0.55, c),
          { tipo: "pantalla", cx: +px.toFixed(1), cy: +py.toFixed(1), agente }];
}

function arbol(x, y, r) {
  const [cx, cy] = iso(x, y, 0);
  return { cx: +cx.toFixed(1), cy: +cy.toFixed(1), r: +(r * ESCALA).toFixed(1) };
}

// Estado → aspecto del agente
export const ESTADOS = {
  trabajando: { nombre: "Trabajando", color: COLOR.senal },
  esperando: { nombre: "Espera aprobación", color: "#c98a0b" },
  reposo: { nombre: "En reposo", color: "#9a9aa2" },
};

export function estadoDemo(departamentos, tick) {
  // Estados de ejemplo, claramente marcados como demostración en la pantalla (no son datos reales)
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
