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

// ---- Resumen de las 16:00 ----

/** Clase de color del encaje (0–100): alto desde 70, medio desde 45. */
export const encajeClase = (n) => (n === null || n === undefined ? "sin" : n >= 70 ? "alto" : n >= 45 ? "medio" : "bajo");

export function diasTexto(d) {
  if (d === null || d === undefined) return "";
  if (d < 0) return "plazo terminado";
  if (d < 1) return "cierra hoy";
  const n = Math.floor(d);
  return n === 1 ? "queda 1 día" : `quedan ${n} días`;
}

const dia = new Intl.DateTimeFormat("es-ES", { dateStyle: "long", timeZone: "Europe/Madrid" });
/** «28 de octubre de 2026» a partir de una fecha «AAAA-MM-DD» (se lee como fecha civil, sin saltos de día por la zona horaria). */
export function fechaCivilTexto(f) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f || "")) return "—";
  return dia.format(new Date(`${f}T12:00:00Z`));
}

/** «de ayer a las 16:00 a hoy a las 16:00», en hora de Madrid, a partir de la ventana del resumen. */
export function ventanaTexto(v) {
  if (!v?.desde || !v?.hasta) return "";
  const hora = new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid" });
  const d = new Date(v.desde), h = new Date(v.hasta);
  if (Number.isNaN(d.getTime()) || Number.isNaN(h.getTime())) return "";
  return `${hora.format(d)} → ${hora.format(h)}`;
}

/** Una línea con las cifras del resumen para la lista de resúmenes y la tarjeta del dashboard. */
export function totalesTexto(t) {
  if (!t) return "";
  const p = [];
  const n = (x, uno, varios) => `${x} ${x === 1 ? uno : varios}`;
  p.push(n(t.oportunidades ?? 0, "oportunidad", "oportunidades"));
  if (t.adjudicaciones) p.push(n(t.adjudicaciones, "adjudicación", "adjudicaciones"));
  if (t.anuladas) p.push(n(t.anuladas, "anulada", "anuladas"));
  return p.join(" · ");
}

export const ORIGEN_RESUMEN = { programada: "de las 16:00", manual: "generado a mano" };

/** Mensaje para una respuesta de error de la API del Cerebro al pedir el resumen. */
export function mensajeResumen(status) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "El resumen de licitaciones es para Dirección y el departamento de Licitaciones.";
  if (status === 404) return "Todavía no hay ningún resumen. Se genera cada día a las 16:00; también puedes generarlo ahora.";
  return "No se ha podido cargar el resumen. Inténtalo en unos minutos.";
}

// ---- Embudo propio (API del Cerebro: /licitaciones/embudo) ----

export const ESTADOS_EMBUDO = [
  ["detectada", "Detectada"], ["en_estudio", "En estudio"], ["presentada", "Presentada"], ["ganada", "Ganada"], ["perdida", "Perdida"], ["descartada", "Descartada"],
];
export const etiquetaEmbudo = (e) => (ESTADOS_EMBUDO.find(([k]) => k === e) || [, e || "—"])[1];

/** Texto del botón que pasa una licitación de un estado del embudo a otro. */
export function accionEmbudo(desde, hacia) {
  if (hacia === "en_estudio") return desde === "descartada" ? "Reabrir (en estudio)" : "Pasar a estudio";
  return { presentada: "Marcar como presentada", ganada: "Marcar como ganada", perdida: "Marcar como perdida…", descartada: "Descartar (no ir)" }[hacia] || etiquetaEmbudo(hacia);
}

/** «40 % (2 de 5)»; con pocas decididas la tasa no significa nada y no se enseña como si fuera una cifra. */
export function tasaExitoTexto(t) {
  if (!t) return "—";
  if (t.valor === null || t.valor === undefined) return `Aún sin datos suficientes (${t.decididas ?? 0} de ${t.minimo ?? 5} decididas)`;
  return `${Math.round(t.valor * 100)} % (${t.ganadas} de ${t.decididas})`;
}

/** Horas como «3 h» o «2,5 días»; null es «—». */
export function horasTexto(h) {
  if (h === null || h === undefined || Number.isNaN(Number(h))) return "—";
  const n = Number(h);
  const f = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });
  return n < 48 ? `${f.format(n)} h` : `${f.format(n / 24)} días`;
}

/** Periodos del dashboard → días que pide la API. */
export const PERIODOS_EMBUDO = [["hoy", 1, "Hoy"], ["7d", 7, "7 días"], ["30d", 30, "30 días"], ["90d", 90, "90 días"]];
export const diasDePeriodo = (p) => (PERIODOS_EMBUDO.find(([k]) => k === p) || PERIODOS_EMBUDO[2])[1];

export function mensajeEmbudo(status) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "El embudo es para Dirección y el departamento de Licitaciones.";
  if (status === 404) return "Esa licitación ya no está en el embudo.";
  if (status === 422) return "Ese cambio no está permitido para el estado actual.";
  if (status === 503) return "No se ha podido consultar el motor de licitaciones. Inténtalo en unos minutos.";
  return "No se ha podido completar la operación. Inténtalo en unos minutos.";
}

/** Aviso cuando el expediente ya no está abierto en el motor (adjudicada, anulada…): quien lo lleva decide qué hacer con él. */
export function avisoEstadoMotor(estado) {
  if (!estado || estado === "abierta" || estado === "anuncio_previo") return null;
  return `En el motor: ${estadoEtiqueta(estado)}`;
}
