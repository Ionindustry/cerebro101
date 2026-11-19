// Ayudas puras del radar de subvenciones (sin React: se prueban con node --test). Todo lo que llega de las fuentes oficiales es TEXTO DE TERCEROS: se muestra como texto, y solo se enlazan http(s).

export const ESTADO_ETIQUETA = {
  NEW: "Nueva", UPDATED: "Modificada", OPENING_SOON: "Abre pronto", OPEN: "Abierta", CLOSING_SOON: "Cierra pronto", CLOSED: "Cerrada", CANCELLED: "Anulada", UNKNOWN: "Estado desconocido",
};
export const ESTADO_CLASE = { OPEN: "ok", OPENING_SOON: "", CLOSING_SOON: "aviso", CLOSED: "no", CANCELLED: "no", UNKNOWN: "" };
export const INSTRUMENTO_ETIQUETA = {
  subvencion: "Subvención", prestamo: "Préstamo", prestamo_participativo: "Préstamo participativo", garantia: "Garantía", aval: "Aval", incentivo_fiscal: "Incentivo fiscal",
  bonificacion: "Bonificación", mixta: "Mixta", premio: "Premio", otro: "Otro",
};
export const AMBITO_ETIQUETA = { nacional: "Nacional", autonomico: "Autonómico", local: "Local", europeo: "Europeo", transfronterizo: "Transfronterizo", otro: "Otro" };
export const CATEGORIAS_RADAR = [
  ["nuevas", "Nuevas"], ["abiertas", "Abiertas"], ["proximas_a_abrir", "Próximas a abrir"], ["proximas_a_cerrar", "Próximas a cerrar"], ["modificadas", "Modificadas"],
];
export const FILTROS_VACIOS = { texto: "", pais: "", estado: "", instrumento: "", fuente: "", importeMin: "", importeMax: "", plazoDesde: "", plazoHasta: "", soloNuevas: false, orden: "" };
export const ESTADO_FUENTE = { PENDING_VERIFICATION: "Pendiente de verificar", VERIFIED: "Verificada", ACTIVE: "Activa", PAUSED: "En pausa", ERROR: "Con error", PLANNED: "Planificada" };

/** Solo se enlazan direcciones http(s): un «javascript:» de una fuente no puede llegar a un href. */
export function urlSegura(u) {
  try {
    const x = new URL(String(u || ""));
    return x.protocol === "http:" || x.protocol === "https:" ? x.href : null;
  } catch { return null; }
}

export function importeTexto(v, moneda = "EUR") {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  try { return n.toLocaleString("es-ES", { style: "currency", currency: moneda || "EUR", maximumFractionDigits: 0 }); } catch { return `${n} ${moneda}`; }
}

export function fechaCorta(f) {
  if (!f) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(f));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "—";
}

/** «cierra en 5 días», «cerró hace 3 días», «sin plazo publicado». `ahora` es un parámetro para poder probarlo. */
export function plazoTexto(deadline, ahora = Date.now()) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(deadline || ""));
  if (!m) return "sin plazo publicado";
  const fin = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  const hoy = new Date(ahora);
  const d = Math.round((fin - Date.UTC(hoy.getUTCFullYear(), hoy.getUTCMonth(), hoy.getUTCDate())) / 86400000);
  if (d === 0) return "cierra hoy";
  if (d === 1) return "cierra mañana";
  if (d > 1) return `cierra en ${d} días`;
  if (d === -1) return "cerró ayer";
  return `cerró hace ${-d} días`;
}

export function filtrosAQuery(f, pagina = 0) {
  const p = new URLSearchParams();
  const pon = (k, v) => { if (v !== "" && v !== null && v !== undefined && v !== false) p.set(k, String(v).trim()); };
  pon("texto", f.texto); pon("pais", f.pais); pon("estado", f.estado); pon("instrumento", f.instrumento); pon("fuente", f.fuente);
  pon("importe_min", f.importeMin); pon("importe_max", f.importeMax); pon("plazo_desde", f.plazoDesde); pon("plazo_hasta", f.plazoHasta);
  if (f.soloNuevas) p.set("solo_nuevas", "true");
  pon("orden", f.orden);
  if (pagina > 0) p.set("pagina", String(pagina));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function novedadEtiqueta(n) { return n === "NEW" ? "Nueva" : n === "UPDATED" ? "Modificada" : ""; }

/** Resumen de la última ejecución de un conector, en una línea. */
export function ejecucionTexto(f) {
  if (!f || !f.run_status) return "Sin ejecuciones todavía";
  const partes = [`${f.fetched ?? 0} leídos`, `${f.inserted ?? 0} nuevos`, `${f.updated ?? 0} modificados`, `${f.unchanged ?? 0} sin cambios`];
  if (f.invalid) partes.push(`${f.invalid} inválidos`);
  return `${f.run_status === "OK" || f.run_status === "ok" ? "Correcta" : f.run_status}: ${partes.join(" · ")}`;
}

/** Por qué no se puede activar una fuente (el servidor lo vuelve a comprobar; esto solo evita un clic inútil). */
export function activableMotivo(f) {
  if (!f) return "Fuente desconocida";
  if (!f.has_connector) return "Esta fuente no tiene conector todavía";
  if (!f.last_success_at) return "Antes hay que hacer una sincronización manual que salga bien";
  return "";
}

export function mensajeError(e) {
  if (!e) return "";
  if (e.status === 403) return e.detalle || "Solo Dirección puede hacer esto.";
  return e.detalle || "No se ha podido completar la operación.";
}
