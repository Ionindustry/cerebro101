// Sección «Licitaciones» del panel: permisos de la pasarela, filtros de búsqueda y formato de lo que devuelve el motor.
// Todo lo que no toca React ni la red está aquí para poder probarlo (test/licitaciones.test.mjs).

// Quién ve la sección (ADR 0007, matriz POR VALIDAR): los grupos que consultan licitaciones, la dirección y la cuenta de servicio.
export const GRUPOS_CON_ACCESO = ["licitaciones", "direccion", "comercial", "telecom", "areas"];

export function conAcceso({ roles = [], grupos = [] } = {}) {
  return roles.includes("direccion") || roles.includes("servicio") || grupos.some((g) => GRUPOS_CON_ACCESO.includes(g));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Lista blanca de la pasarela: solo lectura, y solo lo que el motor sirve hoy. Lo demás ni llega al motor.
export function rutaPermitida(segmentos, metodo) {
  if (metodo !== "GET" || !Array.isArray(segmentos)) return false;
  const [a, b, ...resto] = segmentos;
  if (resto.length > 0) return false;
  if (a === "tenders") return b === undefined || UUID.test(b);
  return a === "ops" && b === "status";
}

/** Decide qué hace la pasarela con una petición. Devuelve null si puede pasar, o {status, codigo, detalle} con la respuesta de error. */
export function decidir({ metodo, segmentos, identidad, hayCredencial }) {
  if (!identidad) return { status: 401, codigo: "no_autenticado", detalle: "Sesión caducada" };
  if (!conAcceso(identidad)) return { status: 403, codigo: "sin_permiso", detalle: "Tu usuario no tiene acceso a Licitaciones" };
  if (!rutaPermitida(segmentos, metodo)) return { status: 404, codigo: "no_encontrado", detalle: "La ruta no existe" };
  if (!hayCredencial) return { status: 503, codigo: "no_disponible", detalle: "El panel no tiene configurada la credencial del motor de licitaciones" };
  return null;
}

export const ESTADOS = [
  ["abierta", "Abierta"], ["anuncio_previo", "Anuncio previo"], ["cerrada", "Cerrada (sin adjudicar)"],
  ["adjudicada", "Adjudicada"], ["formalizada", "Formalizada"], ["desierta", "Desierta"], ["anulada", "Anulada"],
];
export const ORDENES = [["actualizacion", "Más recientes"], ["relevancia", "Relevancia"], ["plazo", "Plazo más próximo"], ["importe", "Mayor importe"]];

export const estadoEtiqueta = (e) => (ESTADOS.find(([k]) => k === e) || [, e || "—"])[1];

const FUENTES = { placsp: "PLACSP", placsp_agregadas: "PLACSP (plataformas agregadas)", placsp_menores: "PLACSP (contratos menores)", ted: "TED", cat: "Cataluña" };
export const nombreFuente = (f) => FUENTES[f] || f || "—";

const num = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const IMPUESTOS = { sin_iva: "sin IVA", con_iva: "con IVA", desconocido: "IVA no indicado" };
const SIGNIFICADOS = {
  valor_estimado: "valor estimado", presupuesto_base: "presupuesto base", adjudicado: "adjudicado", oferta_mas_baja: "oferta más baja",
  oferta_mas_alta: "oferta más alta", modificacion: "modificación", total_con_modificaciones: "total con modificaciones",
};

/** «100.000,50 € · sin IVA». Un importe sin valor numérico válido es «—». */
export function importeTexto(i, conSignificado = false) {
  if (!i || !/^-?\d{1,15}(\.\d{1,4})?$/.test(String(i.valor))) return "—";
  const moneda = i.moneda === "EUR" || !i.moneda ? "€" : i.moneda;
  const partes = [`${num.format(Number(i.valor))} ${moneda}`, IMPUESTOS[i.impuestos]];
  if (conSignificado && SIGNIFICADOS[i.significado]) partes.unshift(SIGNIFICADOS[i.significado]);
  return partes.filter(Boolean).join(" · ");
}

export function fechaTexto(f, conHora = true) {
  const d = f ? new Date(f) : null;
  if (!d || Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("es-ES", conHora ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

/** Solo se enlazan direcciones http(s): lo que llega del motor son datos de terceros y no puede traer un «javascript:». */
export function urlSegura(u) {
  try {
    const x = new URL(u);
    return x.protocol === "https:" || x.protocol === "http:" ? x.href : null;
  } catch {
    return null;
  }
}

const LISTA = /[\s,;]+/;
export const limpiarCpv = (t) => [...new Set(String(t || "").split(LISTA).filter((c) => /^\d{2,8}$/.test(c)))].slice(0, 20);
export const limpiarNuts = (t) => [...new Set(String(t || "").toUpperCase().split(LISTA).filter((c) => /^[A-Z]{2}[0-9A-Z]{0,3}$/.test(c)))].slice(0, 20);
const importeValido = (t) => (/^\d{1,12}([.,]\d{1,2})?$/.test(String(t || "").trim()) ? String(t).trim().replace(",", ".") : "");

export const FILTROS_VACIOS = { q: "", cpv: "", nuts: "", estados: [], importeMin: "", importeMax: "", orden: "", plazoHasta: "" };

/** Filtros del formulario → parámetros de GET /tenders (lo que no es válido se omite en vez de mandar un 400). */
export function filtrosAQuery(f) {
  const p = new URLSearchParams();
  const q = String(f.q || "").trim();
  if (q.length >= 2) p.set("q", q.slice(0, 200));
  for (const c of limpiarCpv(f.cpv)) p.append("cpv", c);
  for (const c of limpiarNuts(f.nuts)) p.append("nuts", c);
  for (const e of f.estados || []) if (ESTADOS.some(([k]) => k === e)) p.append("estado", e);
  const min = importeValido(f.importeMin), max = importeValido(f.importeMax);
  if (min) p.set("importe_min", min);
  if (max) p.set("importe_max", max);
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.plazoHasta || "")) p.set("plazo_hasta", `${f.plazoHasta}T23:59:59Z`);
  const orden = ORDENES.find(([k]) => k === f.orden);
  if (orden && !(orden[0] === "relevancia" && q.length < 2)) p.set("orden", orden[0]);
  return p;
}

/** Parámetros de la URL de la página → filtros del formulario (para compartir un enlace y reproducir la búsqueda). */
export function queryAFiltros(sp) {
  const todos = (k) => sp.getAll(k);
  const plazo = sp.get("plazo_hasta") || "";
  return {
    q: sp.get("q") || "", cpv: todos("cpv").join(" "), nuts: todos("nuts").join(" "), estados: todos("estado"),
    importeMin: sp.get("importe_min") || "", importeMax: sp.get("importe_max") || "", orden: sp.get("orden") || "",
    plazoHasta: /^\d{4}-\d{2}-\d{2}/.test(plazo) ? plazo.slice(0, 10) : "",
  };
}

export function totalTexto(total) {
  if (!total) return "";
  const n = new Intl.NumberFormat("es-ES").format(total.valor);
  if (total.relacion === "gte") return `al menos ${n} resultados`;
  return total.valor === 1 ? "1 resultado" : `${n} resultados`;
}

/** «hace 25 min», «hace 3 h», «hace 2 días» a partir de segundos. */
export function antiguedadTexto(s) {
  if (s === null || s === undefined) return "sin ingesta completa";
  if (s < 90) return "hace un momento";
  if (s < 5400) return `hace ${Math.round(s / 60)} min`;
  if (s < 129600) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} días`;
}

export const ESTADO_MOTOR = {
  ok: { texto: "Al día", clase: "ok" },
  degradado: { texto: "Con retraso", clase: "aviso" },
  caido: { texto: "Sin datos recientes", clase: "caido" },
};
export const estadoMotor = (e) => ESTADO_MOTOR[e] || { texto: "Desconocido", clase: "aviso" };

/** Mensaje para una respuesta de error del motor o de la pasarela (nunca el cuerpo crudo). */
export function mensajeDeError(status) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "Tu usuario no tiene acceso a Licitaciones.";
  if (status === 400) return "La búsqueda no es válida: revisa los filtros.";
  if (status === 404) return "No se ha encontrado.";
  if (status === 429) return "Demasiadas consultas seguidas: espera un momento.";
  return "El motor de licitaciones no está disponible ahora. Inténtalo en unos minutos.";
}
