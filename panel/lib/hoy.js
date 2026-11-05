// «Qué hacer hoy»: el texto y el orden de lo que enseña la pantalla a partir de GET /hoy (puro, para poder probarlo).
export const NIVELES = {
  urgente: { titulo: "Urgente", clase: "anulada" },
  aviso: { titulo: "Hay que mirarlo", clase: "aviso" },
  info: { titulo: "Para tu información", clase: "abierta" },
};
export const CATEGORIAS = { aprobaciones: "Aprobaciones", licitaciones: "Licitaciones", sistema: "Sistema", novedades: "Novedades" };

/** Agrupa los elementos por nivel (en el orden urgente → aviso → info) y da el titular de la pantalla. */
export function hoyResumen(d) {
  if (!d) return { titular: "No se ha podido cargar la lista de hoy.", grupos: [], vacio: false, avisos: [] };
  const items = d.items || [];
  const grupos = ["urgente", "aviso", "info"].map((n) => ({ nivel: n, ...NIVELES[n], items: items.filter((i) => i.nivel === n) })).filter((g) => g.items.length > 0);
  const u = d.urgentes || 0;
  const accion = items.filter((i) => i.nivel !== "info").length;
  const titular = items.length === 0 ? "Todo al día: no hay nada pendiente." : u > 0 ? `${u} ${u === 1 ? "cosa urgente" : "cosas urgentes"}${accion > u ? ` y ${accion - u} más por mirar` : ""}.` : accion > 0 ? `${accion} ${accion === 1 ? "cosa por mirar" : "cosas por mirar"}.` : "Nada urgente; solo novedades.";
  return { titular, grupos, vacio: items.length === 0, avisos: d.avisos || [] };
}

/** Un enlace de la lista solo si es una ruta interna del panel (nunca una dirección externa). */
export const hrefSeguro = (h) => (typeof h === "string" && /^\/(?!\/)[A-Za-z0-9_\-/]*$/.test(h) ? h : null);
