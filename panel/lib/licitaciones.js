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
  if (a === "tenders" && UUID.test(b || "") && resto.length === 1) return resto[0] === "parecidas";     // licitaciones parecidas a una
  if (resto.length > 0) return false;
  if (a === "tenders") return b === undefined || b === "estadisticas" || UUID.test(b);
  if (a === "awards" || a === "competitors" || a === "expiring-contracts") return b === undefined;
  if (a === "organizations") return UUID.test(b || "");                                // la ficha de una organización, siempre por su UUID                   // solo la lista, con sus filtros en la dirección
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
export const MODOS = [["", "Por palabras"], ["significado", "Por significado"], ["hibrido", "Palabras y significado"]];
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

export const FILTROS_VACIOS = { q: "", cpv: "", nuts: "", estados: [], importeMin: "", importeMax: "", orden: "", plazoHasta: "", modo: "" };

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
  // Buscar por significado necesita texto y ordena siempre por cercanía: el orden elegido se ignora para no provocar un error.
  const modo = MODOS.find(([k]) => k && k === f.modo);
  const porSignificado = !!modo && q.length >= 2;
  if (porSignificado) p.set("modo", modo[0]);
  const orden = ORDENES.find(([k]) => k === f.orden);
  if (!porSignificado && orden && !(orden[0] === "relevancia" && q.length < 2)) p.set("orden", orden[0]);
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
    modo: MODOS.some(([k]) => k && k === sp.get("modo")) ? sp.get("modo") : "",
  };
}


// ---- Dashboard de la búsqueda (GET tenders/estadisticas): todo lo que no es pintar está aquí para probarlo ----

/** Los filtros de la búsqueda para las estadísticas: los mismos, sin orden ni modo (se agrega por palabras sobre todo lo que cumple los filtros). */
export function estadisticasQuery(f) {
  const p = filtrosAQuery({ ...f, modo: "", orden: "" });
  return p;
}

const ZONAS = {
  ES511: "Barcelona", ES512: "Girona", ES513: "Lleida", ES514: "Tarragona", ES300: "Madrid", ES521: "Alicante", ES522: "Castellón", ES523: "Valencia",
  ES611: "Almería", ES612: "Cádiz", ES613: "Córdoba", ES618: "Sevilla", ES211: "Álava", ES212: "Gipuzkoa", ES213: "Bizkaia", ES243: "Zaragoza",
};
/** «ES512» → «Girona (ES512)»; un código que no conocemos se deja tal cual; vacío = «Sin zona». */
export const zonaEtiqueta = (c) => (!c ? "Sin zona" : ZONAS[c] ? `${ZONAS[c]} (${c})` : c);

const DIVISIONES_CPV = {
  "03": "Agricultura y pesca", "09": "Combustibles y energía", "14": "Minería", "15": "Alimentación", "18": "Ropa y calzado", "22": "Impresos", "24": "Químicos",
  "30": "Equipos de oficina e informática", "31": "Material eléctrico", "32": "Telecomunicaciones y radio", "33": "Equipos médicos", "34": "Transporte", "35": "Seguridad y defensa",
  "37": "Música, deporte y ocio", "38": "Laboratorio y óptica", "39": "Mobiliario y menaje", "41": "Agua", "42": "Maquinaria industrial", "43": "Maquinaria de obra",
  "44": "Materiales de construcción", "45": "Obras", "48": "Software", "50": "Reparación y mantenimiento", "51": "Instalación", "55": "Hostelería", "60": "Transporte (servicios)",
  "63": "Servicios de apoyo al transporte", "64": "Correos y telecomunicaciones", "65": "Suministros (servicios)", "66": "Servicios financieros", "70": "Inmobiliarios",
  "71": "Arquitectura e ingeniería", "72": "Servicios informáticos", "73": "Investigación y desarrollo", "75": "Administración pública", "76": "Servicios petrolíferos",
  "77": "Agricultura (servicios)", "79": "Servicios a empresas", "80": "Educación", "85": "Sanidad y servicios sociales", "90": "Limpieza y residuos", "92": "Cultura y deporte", "98": "Otros servicios",
};
/** «72» → «Servicios informáticos (72)». */
export const divisionEtiqueta = (c) => (!c ? "Sin CPV" : DIVISIONES_CPV[c] ? `${DIVISIONES_CPV[c]} (${c})` : `CPV ${c}`);

export const TRAMOS_IMPORTE = {
  menos_15k: "Menos de 15.000 €", "15k_50k": "15.000 – 50.000 €", "50k_200k": "50.000 – 200.000 €", "200k_1m": "200.000 € – 1 M€", mas_1m: "Más de 1 M€", sin_importe: "Sin importe",
};
export const tramoEtiqueta = (c) => TRAMOS_IMPORTE[c] || c;

/** «1,5 M€», «250 k€», «980 €»; vacío o no numérico = «—». */
export function importeCorto(v) {
  if (v === "" || v === null || v === undefined || !/^-?\d{1,15}(\.\d{1,4})?$/.test(String(v))) return "—";
  const n = Number(v);
  const f = (x, d) => new Intl.NumberFormat("es-ES", { maximumFractionDigits: d }).format(x);
  if (Math.abs(n) >= 1e6) return `${f(n / 1e6, 1)} M€`;
  if (Math.abs(n) >= 1e4) return `${f(n / 1e3, 0)} k€`;
  return `${f(n, 0)} €`;
}

/** Un reparto → barras: etiqueta legible y anchura (0–100) relativa a la mayor; las vacías se quedan en 0. `etiqueta` convierte el valor en texto. */
export function repartoBarras(grupos, etiqueta = (v) => v) {
  const lista = Array.isArray(grupos) ? grupos : [];
  const max = Math.max(0, ...lista.map((g) => g.cuenta || 0));
  return lista.map((g) => ({ ...g, etiqueta: etiqueta(g.valor), pct: max > 0 ? Math.round(((g.cuenta || 0) / max) * 100) : 0 }));
}

/** Los plazos que vienen por día (AAAA-MM-DD) → los próximos `dias` días seguidos, con ceros donde no vence nada. `hoy` es una fecha AAAA-MM-DD (hora de Madrid). */
export function calendarioPlazos(plazos, hoy, dias = 60) {
  const por = new Map((Array.isArray(plazos) ? plazos : []).map((g) => [g.valor, g.cuenta || 0]));
  const [a, m, d] = String(hoy).split("-").map(Number);
  const out = [];
  for (let i = 0; i < dias; i++) {
    const t = new Date(Date.UTC(a, m - 1, d + i));
    const fecha = t.toISOString().slice(0, 10);
    out.push({ fecha, cuenta: por.get(fecha) || 0, dia: t.getUTCDate(), diaSemana: t.getUTCDay(), esHoy: i === 0 });
  }
  const max = Math.max(0, ...out.map((x) => x.cuenta));
  return out.map((x) => ({ ...x, pct: max > 0 ? Math.round((x.cuenta / max) * 100) : 0 }));
}

/** La fecha de hoy en Madrid como AAAA-MM-DD (los plazos del motor van por día de Madrid). */
export const hoyMadrid = (ahora = new Date()) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Madrid" }).format(ahora);

/** Cambia un filtro desde el dashboard: estados se alternan; zona y CPV se fijan (o se quitan si ya estaban fijados). */
export function filtroDesdeDashboard(f, tipo, valor) {
  if (tipo === "estado") {
    const ya = f.estados.includes(valor);
    return { ...f, estados: ya ? f.estados.filter((e) => e !== valor) : [...f.estados, valor] };
  }
  if (tipo === "zona") return { ...f, nuts: f.nuts.trim() === valor ? "" : valor };
  if (tipo === "cpv") return { ...f, cpv: f.cpv.trim() === valor ? "" : valor };
  return f;
}

/** Las columnas de la tabla que se ordenan en el motor, y el orden que cada una le pide. */
export const COLUMNAS_ORDENABLES = { plazo: "plazo", importe: "importe", actualizada: "actualizacion" };

/** «83 % de parecido» a partir de la cercanía (0 a 1) que da la API; vacío si no hay. */
export function cercaniaTexto(c) {
  return typeof c === "number" && c >= 0 && c <= 1 ? `${Math.round(c * 100)} % de parecido` : "";
}

const MOTIVOS = { mismo_comprador: "Mismo comprador", cpv_comun: "CPV en común" };
export const motivosTexto = (m) => (Array.isArray(m) ? m.map((x) => MOTIVOS[x]).filter(Boolean).join(" · ") : "");

export function mensajeParecidas(status) {
  if (status === 503) return "Todavía no se puede buscar parecidos: la búsqueda por significado no está activada o este expediente aún no se ha analizado. Vuelve a intentarlo en unos minutos.";
  if (status === 404) return "No se encuentra este expediente.";
  return "No se han podido cargar las licitaciones parecidas. Inténtalo de nuevo más tarde.";
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

/** ¿Es el 404 de «esa ruta no existe» (el motor está desactualizado) y no el de «ese dato no existe»? El motor y la pasarela dicen «La ruta no existe». */
export const rutaNoExiste = (e) => e?.status === 404 && /ruta no existe/i.test(String(e?.detalle || ""));

/** Mensaje para una respuesta de error del motor o de la pasarela (nunca el cuerpo crudo). El detalle solo sirve para distinguir los dos 404. */
export function mensajeDeError(status, detalle) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "Tu usuario no tiene acceso a Licitaciones.";
  if (status === 400) return "La búsqueda no es válida: revisa los filtros.";
  if (status === 404) return rutaNoExiste({ status, detalle }) ? "El motor de licitaciones todavía no tiene esta función: hay que actualizarlo (avisa a Tecnología)." : "No se ha encontrado.";
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
  if (t.alertas) p.push(n(t.alertas, "aviso de alertas", "avisos de alertas"));
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

// ---- Viabilidad frente a lo que decidió la gente (resumen del embudo, bloque `viabilidad`): solo cuenta lo ocurrido, no dice quién «acierta» ----

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
const REC_TITULO = { ir: "Recomendó IR", no_ir: "Recomendó NO IR", revisar: "Pidió REVISAR" };

/** Las filas del cuadro: una por recomendación con informes. «Seguimiento» = lo que hizo la gente (ir → se presentó; no ir → se descartó); «resultado» = lo que acabó pasando. */
export function viabilidadFilas(v) {
  const por = v?.por_recomendacion;
  if (!por) return [];
  return ["ir", "no_ir", "revisar"].filter((k) => por[k]?.informes > 0).map((k) => {
    const c = por[k];
    const partes = k === "revisar" ? [] : [plural(c.seguidos, "seguida", "seguidas"), plural(c.contrarios, "en contra", "en contra")];
    if (c.pendientes) partes.push(plural(c.pendientes, "pendiente", "pendientes"));
    const resultado = c.ganadas + c.perdidas ? `${plural(c.ganadas, "ganada", "ganadas")} · ${plural(c.perdidas, "perdida", "perdidas")}` : "—";
    return { clave: k, titulo: REC_TITULO[k], informes: c.informes, seguimiento: partes.join(" · ") || "—", resultado };
  });
}

/** Con pocas licitaciones resueltas, comparar no significa nada: se avisa en vez de enseñarlo como una cifra firme. */
export const viabilidadPocosDatos = (v) => {
  const por = v?.por_recomendacion || {};
  const resueltas = Object.values(por).reduce((n, c) => n + (c.ganadas || 0) + (c.perdidas || 0), 0);
  return resueltas < (v?.minimo ?? 5);
};

// ---- Plazo en el calendario de la empresa (botón «Añadir el plazo al calendario» del embudo) ----

/** Estado del plazo en el calendario: "no" (no está), "ok" (está y coincide con el plazo actual) o "desfasado" (está, pero el plazo ha cambiado desde entonces). */
export function calendarioEstado(x) {
  if (!x?.calendario_plazo) return "no";
  const a = Date.parse(x.calendario_plazo), b = Date.parse(x.fecha_limite);
  return Number.isFinite(a) && Number.isFinite(b) && a === b ? "ok" : "desfasado";
}

/** Se puede poner en el calendario si está viva en el embudo, vinculada al motor y con un plazo que aún no ha pasado. */
export const puedeAnadirAlCalendario = (x, ahora = Date.now()) =>
  Boolean(x?.motor_id) && !["ganada", "perdida", "descartada"].includes(x.estado) && Number.isFinite(Date.parse(x.fecha_limite)) && Date.parse(x.fecha_limite) > ahora;

/** Texto del botón de ponerlo: añadir, o actualizar si el plazo cambió. */
export const textoAnadirCalendario = (x) => (calendarioEstado(x) === "desfasado" ? "Actualizar el plazo en el calendario" : "Añadir el plazo al calendario");

/** Lo que dice la tarjeta cuando el plazo está en el calendario. */
export const textoEnCalendario = (x) =>
  calendarioEstado(x) === "ok" ? "Plazo en el calendario" : calendarioEstado(x) === "desfasado" ? "El plazo en el calendario está desfasado" : "";

export function mensajeCalendario(status) {
  if (status === 422) return "No se puede poner esa licitación en el calendario: ya está resuelta o su plazo ha pasado.";
  if (status === 503) return "No se ha podido escribir en el calendario. Puede que no esté configurado o que no responda; inténtalo en unos minutos.";
  return mensajeEmbudo(status);
}

// ---- Pliegos de una licitación: documentos, antivirus y requisitos con cita (API del Cerebro: /licitaciones/pliegos) ----

const ESTADO_PLIEGO = {
  limpio: ["Analizado: limpio", "abierta"], con_macros: ["Limpio, con macros (solo se lee el texto)", "aviso"], cuarentena: ["En cuarentena, sin analizar", "aviso"],
  no_analizable: ["No analizable (antivirus no disponible, cifrado o demasiado grande)", "aviso"], infectado: ["Infectado: descartado", "anulada"], error: ["Con error", "aviso"],
};
/** Lo que se dice del estado de un documento bajado: {texto, clase}; sin bajar, «Sin descargar». */
export function estadoPliego(d) {
  if (!d) return { texto: "Sin descargar", clase: "" };
  const [texto, clase] = ESTADO_PLIEGO[d.estado] || [d.estado, ""];
  return { texto, clase };
}
/** Se ofrece «Descargar y analizar» si aún no se ha bajado o si hay que reintentarlo (sin analizar, no analizable o sin texto leído); nunca con un infectado. */
export const puedeDescargarPliego = (d) => !d || ["cuarentena", "no_analizable", "error"].includes(d.estado) || (d.disponible && d.paginas == null);
/** Lo que se sabe de la lectura de un documento: «12 páginas», «3 bloques», o el aviso. */
export function lecturaPliego(d) {
  if (!d?.disponible) return "";
  if (d.paginas == null) return d.aviso ? `No se ha podido leer el texto: ${d.aviso}` : "El texto aún no se ha leído";
  const n = d.paginas, u = d.unidad || "página";
  return `${n} ${n === 1 ? u : u === "página" ? "páginas" : u === "bloque" ? "bloques" : "hojas"}${d.aviso ? ` · ${d.aviso}` : ""}`;
}

export const TIPOS_REQUISITO = {
  solvencia_economica: "Solvencia económica", solvencia_tecnica: "Solvencia técnica", administrativo: "Administrativo", tecnico: "Técnico", criterio_automatico: "Criterio automático",
  criterio_juicio_valor: "Criterio de juicio de valor", baja_anormal: "Baja anormal", plazo: "Plazo", garantia: "Garantía", formato_oferta: "Formato de la oferta", otro: "Otro",
};
export const tipoRequisito = (t) => TIPOS_REQUISITO[t] || String(t || "").replace(/_/g, " ");
const ESTADO_REQ = { borrador: ["En borrador: pendiente de revisar", "aviso"], confirmado: ["Confirmado", "abierta"], rechazado: ["Rechazado", "anulada"] };
export const estadoRequisito = (r) => { const [texto, clase] = ESTADO_REQ[r?.estado] || [r?.estado || "—", ""]; return { texto, clase }; };
/** «3 requisitos: 1 confirmado, 2 en borrador». */
export function resumenRequisitos(rs) {
  const n = (rs || []).length;
  if (!n) return "Aún no hay requisitos anotados.";
  const c = (e) => rs.filter((r) => r.estado === e).length;
  const partes = [[c("confirmado"), "confirmado", "confirmados"], [c("borrador"), "en borrador", "en borrador"], [c("rechazado"), "rechazado", "rechazados"]].filter(([k]) => k > 0).map(([k, uno, varios]) => `${k} ${k === 1 ? uno : varios}`);
  return `${n} ${n === 1 ? "requisito" : "requisitos"}: ${partes.join(", ")}`;
}
export const CUMPLIMIENTOS = { pendiente: "Pendiente de valorar", cumple: "Cumple", parcial: "Cumple en parte", no_cumple: "No cumple", no_aplica: "No aplica" };
const CLASE_CUMPLIMIENTO = { pendiente: "aviso", cumple: "abierta", parcial: "aviso", no_cumple: "anulada", no_aplica: "" };
export const cumplimientoEtiqueta = (c) => ({ texto: CUMPLIMIENTOS[c] || c || "—", clase: CLASE_CUMPLIMIENTO[c] ?? "" });
/** «Parcial» y «no cumple» exigen decir por qué (el servidor también lo comprueba). */
export const cumplimientoNecesitaNota = (c) => c === "parcial" || c === "no_cumple";
/** Resumen de la matriz: «5 requisitos: 3 cumplen, 1 en parte, 1 pendiente». */
export function resumenMatriz(m) {
  if (!m || !m.total) return "Aún no hay requisitos confirmados: confirma los requisitos para formar la matriz.";
  const r = m.resumen || {};
  const partes = [[r.cumple, "cumple", "cumplen"], [r.parcial, "en parte", "en parte"], [r.no_cumple, "no cumple", "no cumplen"], [r.no_aplica, "no aplica", "no aplican"], [r.pendiente, "pendiente", "pendientes"]]
    .filter(([k]) => k > 0).map(([k, uno, varios]) => `${k} ${k === 1 ? uno : varios}`);
  return `${m.total} ${m.total === 1 ? "requisito" : "requisitos"}: ${partes.join(", ")}`;
}
/** La matriz a partir de los requisitos de la ficha: solo los confirmados, con el resumen por cumplimiento (como la del servidor). */
export function matrizDe(requisitos) {
  const filas = (requisitos || []).filter((r) => r.estado === "confirmado");
  const resumen = Object.fromEntries(Object.keys(CUMPLIMIENTOS).map((c) => [c, filas.filter((r) => (r.cumplimiento || "pendiente") === c).length]));
  return { total: filas.length, resumen, filas, borradores: (requisitos || []).filter((r) => r.estado === "borrador").length };
}
/** Una celda de CSV: entre comillas, con las comillas dobladas, y sin que una hoja de cálculo la tome por una fórmula (= + - @ al principio). */
export function celdaCsv(v) {
  let t = String(v ?? "").replace(/\r?\n/g, " ");
  if (/^[=+\-@\t]/.test(t)) t = `'${t}`;
  return `"${t.replace(/"/g, '""')}"`;
}
/** La matriz como CSV (separado por «;», lo que espera Excel en español) con BOM para los acentos. */
export function matrizCsv(m) {
  const cab = ["Tipo", "Requisito", "Valor", "Cita literal", "Dónde", "Cumplimiento", "Motivo", "Valorado por"];
  const filas = (m?.filas || []).map((f) => [tipoRequisito(f.tipo), f.resumen, f.valor, f.cita, lugarCita(f), CUMPLIMIENTOS[f.cumplimiento] || f.cumplimiento, f.cumplimiento_nota, f.cumplimiento_por || ""]);
  return "\uFEFF" + [cab, ...filas].map((fila) => fila.map(celdaCsv).join(";")).join("\r\n");
}
/** Dónde está una cita: «Pliego administrativo, página 12» (o «bloque»/«hoja»). */
export const lugarCita = (r) => `${r.nombre || `Documento ${r.documento}`}, ${r.unidad || "página"} ${r.pagina}`;

export function mensajePliegos(status) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "Los pliegos son para Dirección y el departamento de Licitaciones, y solo de las plataformas de contratación admitidas.";
  if (status === 404) return "No existe esa licitación o ese requisito.";
  if (status === 422) return "No se puede hacer eso con este documento (no está bajado y analizado, supera el tamaño o se ha llegado al máximo de descargas del día).";
  if (status === 503) return "No se ha podido consultar el motor de licitaciones o el antivirus. Inténtalo en unos minutos.";
  return "No se ha podido completar la operación. Inténtalo en unos minutos.";
}

// ---- Simulador de ofertas (API del Cerebro: POST /licitaciones/simulador) ----

/** Una probabilidad 0-1 como «45 %». */
export const porcentaje = (p) => (p === null || p === undefined || Number.isNaN(Number(p)) ? "—" : `${Math.round(Number(p) * 100)} %`);
/** «45 % (30–61 %)»: la probabilidad con su rango de incertidumbre. */
export const probabilidadConRango = (f) => `${porcentaje(f.p_ganar)} (${Math.round(f.p_ganar_min * 100)}–${porcentaje(f.p_ganar_max)})`;
/** Hasta `max` filas de la curva, repartidas, sin perder la primera, la última ni la recomendada. */
export function filasDeCurva(r, max = 12) {
  const c = r?.curva || [];
  if (c.length <= max) return c;
  const paso = (c.length - 1) / (max - 1);
  const idx = new Set(Array.from({ length: max }, (_, i) => Math.round(i * paso)));
  const reco = r?.recomendacion ? c.findIndex((f) => f.baja_pct === r.recomendacion.baja_pct) : -1;
  if (reco >= 0) idx.add(reco);
  return [...idx].sort((a, b) => a - b).map((i) => c[i]);
}
/** Si el resultado sirve para decidir o solo orienta, y por qué. */
export function aptitudSimulacion(r) {
  if (!r) return { apto: false, texto: "" };
  if (r.apto_para_decidir) return { apto: true, texto: "Apto para decidir: muestra suficiente, comprobado con el pasado y el precio decide solo." };
  const motivos = [];
  if (!r.muestra?.suficiente) motivos.push(`pocos concursos parecidos (${r.muestra?.n ?? 0})`);
  if (r.backtest && !r.backtest.apto) motivos.push(r.backtest.motivo || "no supera la comprobación con el pasado");
  if (r.licitacion?.peso_juicio_de_valor > 0) motivos.push(`el juicio de valor pesa un ${r.licitacion.peso_juicio_de_valor} %`);
  return { apto: false, texto: `Solo orientativo, no decide por sí solo: ${motivos.join("; ") || "no cumple lo acordado"}.` };
}
export function mensajeSimulador(status, detalle = "") {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "El simulador es para Dirección y el departamento de Licitaciones.";
  if (status === 404) return "No existe esa licitación.";
  if (status === 422 && detalle) return detalle;           // son mensajes pensados para la persona (sin presupuesto, presupuesto del ERP que no existe…)
  if (status === 422) return "No se puede simular esta licitación (sin presupuesto o CPV, o sin concursos parecidos en el histórico) o el coste no es válido.";
  if (status === 503) return "No se ha podido consultar el motor de licitaciones. Inténtalo en unos minutos.";
  return "No se ha podido simular. Inténtalo en unos minutos.";
}
/** El coste escrito («150.000», «150000,50») como número, o null si está vacío o no vale. */
export function costeDeTexto(t) {
  const x = String(t ?? "").trim().replace(/\s|€/g, "");
  if (!x) return null;
  const n = Number(/,\d{1,2}$/.test(x) ? x.replace(/\./g, "").replace(",", ".") : x.replace(/[.,](?=\d{3}(\D|$))/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

export const FORMULAS_PRECIO = [
  ["inversa", "Proporcionalidad inversa (la oferta más barata se lleva todos los puntos)"],
  ["proporcional_baja", "Proporcional a la baja (la mayor baja se lleva todos los puntos)"],
  ["lineal_umbral", "Lineal hasta una baja tope"],
];

/** El formulario de reglas del pliego → cuerpo del POST, o {error} con lo que falta. Los números admiten coma decimal. */
export function reglasAEnvio(id, f) {
  if (!FORMULAS_PRECIO.some(([k]) => k === f.formula)) return { error: "Elige cómo puntúa el pliego el precio" };
  const puntos = costeDeTexto(f.puntos), total = costeDeTexto(f.total) ?? 100;
  if (puntos === null) return { error: "Escribe los puntos que da el precio (p. ej. 51)" };
  if (puntos > total) return { error: "Los puntos del precio no pueden superar los puntos totales" };
  const cuerpo = { motor_id: id, formula: f.formula, puntos_precio: puntos, puntos_total: total, nota: String(f.nota || "").trim().slice(0, 500) };
  if (f.formula === "lineal_umbral") {
    const tope = costeDeTexto(f.tope);
    if (tope === null || tope > 100) return { error: "Escribe la baja tope (%), la que ya no puntúa más" };
    cuerpo.baja_tope_pct = tope;
  }
  if (String(f.anormal ?? "").trim()) {
    const a = costeDeTexto(f.anormal);
    if (a === null || a > 100) return { error: "El umbral de baja anormal debe ser un porcentaje, p. ej. 25" };
    cuerpo.baja_anormal_pct = a;
  }
  return { cuerpo };
}

/** Las reglas guardadas → el estado del formulario (todo texto). */
export function reglasAFormulario(r) {
  const t = (x) => (x == null ? "" : String(x).replace(".", ","));
  return { formula: r?.formula || "inversa", puntos: t(r?.puntos_precio), total: r?.puntos_total && r.puntos_total !== 100 ? t(r.puntos_total) : "", tope: t(r?.baja_tope_pct), anormal: t(r?.baja_anormal_pct), nota: r?.nota || "" };
}

export function mensajeReglas(status) {
  if (status === 403) return "Solo Dirección y el departamento de Licitaciones pueden anotar las reglas.";
  if (status === 422) return "Alguno de los datos no es válido. Revisa los números.";
  return "No se han podido guardar las reglas. Inténtalo de nuevo más tarde.";
}

/** Cómo salió el coste traído del ERP, en una frase. */
export function costeErpTexto(c) {
  if (!c) return "";
  const n = (c.lineas || []).length, f = (c.sin_coste || []).length;
  return `Coste del presupuesto ${c.presupuesto} en el ERP: ${n} línea${n === 1 ? "" : "s"} con coste${f ? `; ${f} sin coste (no contadas: el coste real será mayor)` : ""}.`;
}

// ---- Oferta de la licitación (API del Cerebro: /licitaciones/ofertas) ----

export const SOBRES_OFERTA = [["administrativo", "Sobre administrativo"], ["tecnico", "Sobre técnico"], ["economico", "Sobre económico"]];
const ESTADOS_SECCION = { vacia: "Sin redactar", borrador: "Borrador", revisada: "Revisada", aprobada: "Aprobada" };
export const estadoSeccionEtiqueta = (e) => ESTADOS_SECCION[e] || e || "—";
export const claseSeccion = (e) => (e === "aprobada" ? "abierta" : e === "revisada" ? "" : "aviso");

/** Quién escribió la versión actual de una sección, en una frase. */
export function autorSeccionTexto(s) {
  const por = String(s?.por || "");
  if (!por || !s?.version) return "";
  return por.startsWith("agente:") ? `Redactada por el agente ${por.slice(7)}` : `Escrita por ${por}`;
}

/** «3 sin redactar · 2 borradores · 1 aprobada», o vacío. */
export function resumenOfertaTexto(o) {
  const r = o?.resumen;
  if (!r) return "";
  const t = [[r.vacia, "sin redactar", "sin redactar"], [r.borrador, "borrador", "borradores"], [r.revisada, "revisada", "revisadas"], [r.aprobada, "aprobada", "aprobadas"]];
  return t.filter(([n]) => n > 0).map(([n, uno, varios]) => `${n} ${n === 1 ? uno : varios}`).join(" · ");
}

/** El formulario del precio → cuerpo del POST, o {error}. El IVA vacío es 21 %. */
export function precioAEnvio(f) {
  const precio = costeDeTexto(f.precio);
  if (precio === null) return { error: "Escribe el precio de la oferta sin IVA, p. ej. 125.000,50" };
  const iva = String(f.iva ?? "").trim() === "" ? 21 : Number(String(f.iva).replace(",", "."));
  if (!Number.isFinite(iva) || iva < 0 || iva > 100) return { error: "El IVA debe ser un porcentaje entre 0 y 100" };
  return { cuerpo: { precio, iva_pct: iva } };
}

export function mensajeOferta(status, detalle = "") {
  if (status === 403) return "Solo Dirección y el departamento de Licitaciones pueden trabajar con la oferta.";
  if ((status === 422 || status === 404) && detalle) return detalle;
  if (status === 503) return "No se ha podido consultar el motor de licitaciones. Inténtalo en unos minutos.";
  return "No se ha podido completar la operación. Inténtalo de nuevo más tarde.";
}

/** Qué falta antes de presentar la oferta: lista de frases (vacía si está todo). */
export function pendientesOferta(o) {
  if (!o?.existe) return [];
  const p = [];
  const sin = (o.secciones || []).filter((s) => s.estado === "vacia").length;
  const noAprob = (o.secciones || []).filter((s) => s.estado !== "aprobada" && s.estado !== "vacia").length;
  if (sin) p.push(`${sin} sección${sin === 1 ? "" : "es"} sin redactar`);
  if (noAprob) p.push(`${noAprob} sección${noAprob === 1 ? "" : "es"} sin aprobar`);
  if (o.precio_sin_iva == null) p.push("falta fijar el precio");
  const c = o.cobertura?.sin_cubrir?.length || 0;
  if (c) p.push(`${c} requisito${c === 1 ? "" : "s"} técnico${c === 1 ? "" : "s"} del pliego sin cubrir`);
  return p;
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
  if (status === 409) return "Ya hay un informe en curso o ya existe: actualiza la página.";
  if (status === 422) return "Ese cambio no está permitido para el estado actual.";
  if (status === 503) return "No se ha podido consultar el motor de licitaciones. Inténtalo en unos minutos.";
  return "No se ha podido completar la operación. Inténtalo en unos minutos.";
}

/** Aviso cuando el expediente ya no está abierto en el motor (adjudicada, anulada…): quien lo lleva decide qué hacer con él. */
export function avisoEstadoMotor(estado) {
  if (!estado || estado === "abierta" || estado === "anuncio_previo") return null;
  return `En el motor: ${estadoEtiqueta(estado)}`;
}

// ---- Alertas guardadas y avisos (API del Cerebro: /licitaciones/alertas, /licitaciones/avisos) ----

export const EVENTOS_ALERTA = [
  ["licitacion.nueva", "Nueva licitación"], ["licitacion.modificada", "Modificada"], ["licitacion.adjudicada", "Adjudicada"],
  ["licitacion.formalizada", "Formalizada"], ["licitacion.anulada", "Anulada"],
];
const ETIQUETA_COMPETENCIA = "Competencia: adjudicada";
export const eventoEtiqueta = (e) => e === "competencia.adjudicada" ? ETIQUETA_COMPETENCIA : (EVENTOS_ALERTA.find(([k]) => k === e) || [, String(e || "").replace("licitacion.", "")])[1];

/** Los filtros del buscador (formulario) → el filtro de una alerta (lo que no es válido se omite; sin criterios queda vacío y la alerta no se puede guardar). */
export function filtroDeAlerta(f) {
  const out = {};
  const q = String(f.q || "").trim();
  if (q.length >= 2) out.q = q.slice(0, 200);
  const cpv = limpiarCpv(f.cpv), nuts = limpiarNuts(f.nuts);
  if (cpv.length) out.cpv = cpv;
  if (nuts.length) out.nuts = nuts;
  const estados = (f.estados || []).filter((e) => ESTADOS.some(([k]) => k === e));
  if (estados.length) out.estado = estados;
  const min = importeValido(f.importeMin), max = importeValido(f.importeMax);
  if (min) out.importe_min = min;
  if (max) out.importe_max = max;
  const comprador = limpiarNifs(f.comprador);
  if (comprador.length) out.comprador = comprador;
  return out;
}

const euros = (v) => `${new Intl.NumberFormat("es-ES").format(Number(v))} €`;

/** Una frase con lo que busca una alerta: «texto "cámaras" · CPV 32323500 · zona ES512 · importe desde 100.000 €». */
export function filtroTexto(f) {
  if (!f || typeof f !== "object") return "";
  const p = [];
  if (f.q) p.push(`texto «${f.q}»`);
  if (f.cpv?.length) p.push(`CPV ${f.cpv.join(", ")}`);
  if (f.nuts?.length) p.push(`zona ${f.nuts.join(", ")}`);
  if (f.estado?.length) p.push(`estado ${f.estado.map(estadoEtiqueta).join(" o ").toLowerCase()}`);
  if (f.importe_min) p.push(`desde ${euros(f.importe_min)}`);
  if (f.importe_max) p.push(`hasta ${euros(f.importe_max)}`);
  if (f.comprador?.length) p.push(`comprador ${f.comprador.join(", ")}`);
  if (f.procedimiento?.length) p.push(`procedimiento ${f.procedimiento.join(", ").replace(/_/g, " ")}`);
  return p.join(" · ");
}

// ---- Alertas de competencia: avisan cuando un competidor gana (solo adjudicaciones) ----

export const TIPOS_ALERTA = [["licitacion", "Licitaciones: nuevas, cambios, adjudicaciones…"], ["competencia", "Competencia: avisar cuando un competidor gane"]];
/** Los NIF de la lista de competidores escrita en el formulario (separados por espacios, comas o líneas); lo que no es un NIF se omite. Máximo 20. */
const FORMA_NIF = /^([A-Z][0-9]{7}[0-9A-Z]|[0-9]{8}[A-Z]|[XYZ][0-9]{7}[A-Z])$/;          // una palabra de 9 letras («Seguridad») no es un NIF
export const competidoresDeTexto = (t) => limpiarNifs(t).map((c) => c.replace(/^nif:/, "")).filter((c) => FORMA_NIF.test(c));
/** Una alerta de competencia necesita competidores concretos o, si no, algún criterio de mercado (CPV, zona, comprador…): sin ninguno avisaría de toda adjudicación. */
export const competenciaGuardable = (f) => competidoresDeTexto(f.competidores).length > 0 || Object.keys(filtroDeAlerta(f)).length > 0;
export const esCompetencia = (a) => a?.tipo === "competencia";
/** Quién tiene que ganar para que salte la alerta: «B12345678, A08000143» o «cualquier adjudicatario». */
export const vigilaTexto = (a) => (a?.competidores?.length ? a.competidores.join(", ") : a?.solo_nuevos ? "empresas nuevas en el mercado" : "cualquier adjudicatario");
/** Las líneas «Ganó X (NIF) · 90.000 € sin IVA» de un aviso de competencia. */
export const ganadoresTexto = (detalle) =>
  (detalle?.ganadores || []).map((g) => ["Ganó " + (g.nombre || "(sin nombre)"), g.nif, g.importe != null ? `${euros(g.importe)} sin IVA` : "", g.lote && g.lote !== "1" ? `lote ${g.lote}` : "", detalle?.nuevos ? "empresa nueva en este mercado" : ""].filter(Boolean).join(" · "));

export const ambitoTexto = (a) => (a.ambito === "departamento" ? `Departamento ${a.departamento}` : "Personal");

/** «3 avisos sin leer», «1 aviso sin leer», «Sin avisos nuevos». */
export const sinLeerTexto = (n) => (!n ? "Sin avisos nuevos" : n === 1 ? "1 aviso sin leer" : `${n} avisos sin leer`);

export function mensajeAlertas(status) {
  if (status === 401) return "Tu sesión ha caducado.";
  if (status === 403) return "No tienes permiso para esto. Las alertas de un departamento las crea su responsable o Dirección.";
  if (status === 404) return "Esa alerta ya no existe.";
  if (status === 422) return "Revisa los datos de la alerta: necesita un nombre, al menos un criterio de búsqueda y un evento (o, en competencia, competidores o un criterio de mercado); por correo, solo a direcciones @101.cat.";
  return "No se ha podido completar la operación. Inténtalo en unos minutos.";
}

export const CANALES_ALERTA = [["panel", "Solo en el panel"], ["resumen_diario", "En el panel y en el resumen de las 16:00"], ["correo", "En el panel y por correo"]];
/** El resumen solo admite alertas de departamento; el correo, cualquiera (personal o de departamento). */
export const canalesDe = (ambito) => CANALES_ALERTA.filter(([k]) => k !== "resumen_diario" || ambito === "departamento");
/** Los avisos por correo salen solo a direcciones de la empresa: lo mismo que comprueba la API (config/buzones.yaml). */
export const DOMINIO_CORREO = "101.cat";
export const correoValido = (t) => /^[a-z0-9._%+-]{1,64}@101\.cat$/.test(String(t || "").trim().toLowerCase());
/** Lo que se muestra del canal de una alerta: en «correo», a qué dirección. */
export const canalDeAlertaTexto = (a) => (a?.canal === "correo" ? `Por correo a ${a.correo_destino || "?"}` : a?.canal === "resumen_diario" ? canalEtiqueta("resumen_diario") : "");
export const canalEtiqueta = (c) => (CANALES_ALERTA.find(([k]) => k === c) || [, c || "—"])[1];

/** Solo una alerta de departamento puede salir en el resumen (lo ven Dirección y Licitaciones): una personal, nunca. */
export const admiteResumen = (a) => a?.ambito === "departamento";

/** «3 avisos» / «se detallan 2 de 5»: lo que se cuenta de una alerta en el resumen. */
export function avisosDeAlertaTexto(g) {
  if (!g) return "";
  const t = `${g.total} ${g.total === 1 ? "aviso" : "avisos"}`;
  return g.total > (g.avisos?.length ?? 0) ? `${t} (se detallan ${g.avisos.length})` : t;
}

// ---- Informe de Viabilidad (rastreo diario del embudo): consultivo, nunca decide ----

const VIABILIDAD = { ir: ["IR", "abierta"], no_ir: ["NO IR", "anulada"], revisar: ["REVISAR", "aviso"], sin_recomendacion: ["Sin recomendación", ""] };

/** La etiqueta del informe de Viabilidad de una licitación: {texto, clase}, o null si aún no hay informe. */
export function viabilidadEtiqueta(v) {
  if (!v || typeof v !== "object") return null;
  const [texto, clase] = VIABILIDAD[v.recomendacion] || VIABILIDAD.sin_recomendacion;
  return { texto: `Viabilidad: ${texto}`, clase };
}

/** Una petición «en curso» más vieja que esto se da por perdida (el trabajador se cayó): igual que en la API, para no esperar para siempre. */
export const VENTANA_PETICION_MS = 20 * 60 * 1000;

/** Estado de la petición del informe de una licitación: "en_curso", "error" (con su texto) o null. */
export function peticionViabilidad(x, ahora = Date.now()) {
  const p = x?.viabilidad_peticion;
  if (!p || typeof p !== "object") return null;
  if (p.estado === "error") return { estado: "error", error: p.error || "No se ha podido generar el informe." };
  const t = Date.parse(p.en);
  if (p.estado === "en_curso" && Number.isFinite(t) && ahora - t < VENTANA_PETICION_MS) return { estado: "en_curso" };
  return null;
}

/** Se puede pedir el informe si la licitación está viva en el embudo, vinculada al motor y sin otra petición en curso. */
export const puedePedirViabilidad = (x, ahora = Date.now()) =>
  Boolean(x?.motor_id) && !["ganada", "perdida", "descartada"].includes(x.estado) && peticionViabilidad(x, ahora)?.estado !== "en_curso";

/** Texto del botón: pedir, o volver a pedir (sustituye el informe anterior). */
export const textoPedirViabilidad = (x) => (x?.viabilidad ? "Volver a pedir el informe de viabilidad" : "Pedir informe de viabilidad");

/** Si alguna licitación tiene el informe en curso, la lista se refresca sola. */
export const hayPeticionEnCurso = (items, ahora = Date.now()) => (items || []).some((x) => peticionViabilidad(x, ahora)?.estado === "en_curso");

// ---- Competencia (GET /competitors y /awards del motor) ----

export const ORDENES_COMPETENCIA = [["importe", "Mayor importe adjudicado"], ["contratos", "Más contratos ganados"]];
export const COMPETENCIA_VACIA = { cpv: "", nuts: "", comprador: "", desde: "", hasta: "", orden: "" };
/** Atajos de mercado para empezar (CPV de las áreas de 101.cat; el usuario puede escribir los suyos). */
export const MERCADOS_EJEMPLO = [["Informática y software", "72"], ["Videovigilancia", "35125"], ["Telecomunicaciones", "64200000"], ["Mantenimiento de equipos", "50300000"]];

/** NIF del comprador tal como lo pide el motor («nif:P1708500E»); lo que no tiene 9 letras o cifras se omite. */
export const limpiarNifs = (t) => [...new Set(String(t || "").split(LISTA).map((c) => c.replace(/^nif:/i, "")).filter((c) => /^[0-9A-Za-z]{9}$/.test(c)).map((c) => `nif:${c.toUpperCase()}`))].slice(0, 20);
const fechaValida = (t) => {                                    // «2027-02-30» no existe: Date lo corrige a marzo, así que se compara de vuelta
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t || "")) return "";
  const d = new Date(`${t}T12:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === t ? t : "";
};

/** El motor exige acotar el mercado con al menos un CPV, una zona o un comprador: sin eso no se le pregunta. */
export const competenciaAcotada = (f) => limpiarCpv(f.cpv).length + limpiarNuts(f.nuts).length + limpiarNifs(f.comprador).length > 0;

/** Filtros del formulario → parámetros de GET /competitors. */
export function competenciaAQuery(f) {
  const p = new URLSearchParams();
  for (const c of limpiarCpv(f.cpv)) p.append("cpv", c);
  for (const c of limpiarNuts(f.nuts)) p.append("nuts", c);
  for (const c of limpiarNifs(f.comprador)) p.append("comprador", c);
  const desde = fechaValida(f.desde), hasta = fechaValida(f.hasta);
  if (desde) p.set("desde", desde);
  if (hasta && (!desde || desde <= hasta)) p.set("hasta", hasta);
  if (ORDENES_COMPETENCIA.some(([k]) => k === f.orden)) p.set("orden", f.orden);
  return p;
}

/** Parámetros de la dirección de la página → filtros del formulario. */
export function queryACompetencia(sp) {
  return {
    cpv: sp.getAll("cpv").join(" "), nuts: sp.getAll("nuts").join(" "), comprador: sp.getAll("comprador").map((c) => c.replace(/^nif:/i, "")).join(" "),
    desde: sp.get("desde") || "", hasta: sp.get("hasta") || "", orden: sp.get("orden") || "",
  };
}

/** Las últimas adjudicaciones de una empresa EN EL MISMO MERCADO que se está mirando: mismos filtros, más el adjudicatario. */
export function adjudicacionesDeCompetidor(filtros, organizacionId, limite = 5) {
  const p = competenciaAQuery(filtros);
  p.delete("orden");
  if (p.has("desde")) { p.set("adjudicada_desde", p.get("desde")); p.delete("desde"); }
  if (p.has("hasta")) { p.set("adjudicada_hasta", p.get("hasta")); p.delete("hasta"); }
  p.set("adjudicatario", organizacionId);
  p.set("resultado", "adjudicado");
  p.set("orden", "fecha");
  p.set("limit", String(limite));
  return p;
}

const pct = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
/** Cuota de mercado (0–1) como porcentaje: «66,7 %»; lo que no llega al 0,1 % es «<0,1 %». */
export function cuotaTexto(c) {
  if (typeof c !== "number" || !Number.isFinite(c) || c < 0 || c > 1.0001) return "—";
  if (c > 0 && c < 0.001) return "<0,1 %";
  return `${pct.format(c * 100)} %`;
}

/** Baja (0–1) como porcentaje sobre el presupuesto base; sin dato (presupuesto no fiable) es «—». */
export function bajaTexto(b) {
  if (typeof b !== "number" || !Number.isFinite(b) || b < 0 || b > 1) return "—";
  return `${pct.format(b * 100)} %`;
}

export const TENDENCIAS = {
  sube: { texto: "Sube", clase: "ok", ayuda: "Más contratos en los últimos 12 meses que en los 12 anteriores" },
  estable: { texto: "Estable", clase: "", ayuda: "Los mismos contratos que en los 12 meses anteriores" },
  baja: { texto: "Baja", clase: "caido", ayuda: "Menos contratos en los últimos 12 meses que en los 12 anteriores" },
  sin_datos: { texto: "Sin datos", clase: "", ayuda: "Menos de 3 contratos: no hay base para hablar de tendencia" },
};
export const tendenciaEtiqueta = (t) => TENDENCIAS[t] || TENDENCIAS.sin_datos;

const MUESTRA_MINIMA = 10;
const mes = new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" });
const mesTexto = (f) => (/^\d{4}-\d{2}-\d{2}$/.test(f || "") ? mes.format(new Date(`${f}T12:00:00Z`)) : "");

/** Cuántos datos hay detrás de las cifras (siempre visible): «34 adjudicaciones entre marzo de 2025 y septiembre de 2026». */
export function muestraTexto(m) {
  if (!m || !m.adjudicaciones) return "No hay adjudicaciones en este mercado y periodo.";
  const n = new Intl.NumberFormat("es-ES").format(m.adjudicaciones);
  const base = m.adjudicaciones === 1 ? "1 adjudicación" : `${n} adjudicaciones`;
  const d = mesTexto(m.desde), h = mesTexto(m.hasta);
  return d && h ? `${base} entre ${d} y ${h}` : base;
}

/** Con pocas adjudicaciones las cuotas y las bajas son orientativas: la página lo avisa. */
export const muestraPoca = (m) => Boolean(m) && m.adjudicaciones > 0 && m.adjudicaciones < MUESTRA_MINIMA;

/** Resumen de los filtros del mercado para el título («CPV 72 · ES512 · desde 2025-01-01»). */
export function mercadoTexto(f) {
  const p = [];
  const cpv = limpiarCpv(f.cpv), nuts = limpiarNuts(f.nuts), nifs = limpiarNifs(f.comprador);
  if (cpv.length) p.push(`CPV ${cpv.join(", ")}`);
  if (nuts.length) p.push(`zona ${nuts.join(", ")}`);
  if (nifs.length) p.push(`comprador ${nifs.map((n) => n.slice(4)).join(", ")}`);
  if (fechaValida(f.desde)) p.push(`desde ${f.desde}`);
  if (fechaValida(f.hasta)) p.push(`hasta ${f.hasta}`);
  return p.join(" · ");
}


// ---- Contratos que vencen (GET /expiring-contracts del motor) ----

export const VENCEN_VACIO = { cpv: "", nuts: "", comprador: "", importeMin: "", desde: "", hasta: "", conProrrogas: false };
const MAX_MESES_VENCEN = 36;

const sumarMeses = (f, n) => { const d = new Date(`${f}T12:00:00Z`); d.setUTCMonth(d.getUTCMonth() + n); return d.toISOString().slice(0, 10); };

/** Mensaje si el periodo pedido no lo admite el motor (desde posterior a hasta, o más de 36 meses); null si está bien. */
export function vencenProblema(f) {
  const desde = fechaValida(f.desde), hasta = fechaValida(f.hasta);
  if (desde && hasta && desde > hasta) return "«Desde» no puede ser posterior a «hasta».";
  if (desde && hasta && hasta > sumarMeses(desde, MAX_MESES_VENCEN)) return "El periodo no puede pasar de 36 meses.";
  return null;
}

/** Filtros del formulario → parámetros de GET /expiring-contracts. Sin fechas, el motor mira de hoy + 3 meses a hoy + 12 meses. */
export function vencenAQuery(f) {
  const p = new URLSearchParams();
  for (const c of limpiarCpv(f.cpv)) p.append("cpv", c);
  for (const c of limpiarNuts(f.nuts)) p.append("nuts", c);
  for (const c of limpiarNifs(f.comprador)) p.append("comprador", c);
  const min = importeValido(f.importeMin);
  if (min) p.set("importe_min", min);
  const desde = fechaValida(f.desde), hasta = fechaValida(f.hasta);
  if (desde) p.set("vence_desde", desde);
  if (hasta) p.set("vence_hasta", hasta);
  if (f.conProrrogas) p.set("con_prorrogas", "true");
  return p;
}

/** Parámetros de la dirección de la página → filtros del formulario. */
export function queryAVencen(sp) {
  return {
    cpv: sp.getAll("cpv").join(" "), nuts: sp.getAll("nuts").join(" "), comprador: sp.getAll("comprador").map((c) => c.replace(/^nif:/i, "")).join(" "),
    importeMin: sp.get("importe_min") || "", desde: sp.get("vence_desde") || "", hasta: sp.get("vence_hasta") || "", conProrrogas: sp.get("con_prorrogas") === "true",
  };
}

const mesLargo = new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" });
/** Agrupa contratos (ya ordenados por fecha de fin) por mes de fin: [{ mes: «2027-02», titulo: «febrero de 2027», items }]. */
export function agruparPorMes(items) {
  const grupos = [];
  for (const x of items || []) {
    const mes = /^\d{4}-\d{2}/.test(x.fecha_fin || "") ? x.fecha_fin.slice(0, 7) : "sin-fecha";
    let g = grupos[grupos.length - 1];
    if (!g || g.mes !== mes) {
      g = { mes, titulo: mes === "sin-fecha" ? "Sin fecha" : mesLargo.format(new Date(`${mes}-15T12:00:00Z`)), items: [] };
      grupos.push(g);
    }
    g.items.push(x);
  }
  return grupos;
}

/** «ya ha terminado», «termina hoy», «en 12 días», «en 4 meses» a partir de la fecha de fin y de «hoy» (ambas «AAAA-MM-DD»). */
export function venceEnTexto(fin, hoy) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fin || "") || !/^\d{4}-\d{2}-\d{2}$/.test(hoy || "")) return "";
  const dias = Math.round((new Date(`${fin}T12:00:00Z`) - new Date(`${hoy}T12:00:00Z`)) / 86400000);
  if (dias < 0) return "ya ha terminado";
  if (dias === 0) return "termina hoy";
  if (dias === 1) return "termina mañana";
  if (dias < 60) return `en ${dias} días`;
  const meses = Math.round(dias / 30.44);
  return meses < 24 ? `en ${meses} meses` : `en ${Math.round(meses / 12)} años`;
}

/** Cuánto fiarse de la fecha de fin: depende de qué fecha de inicio había (0,9 entrada en vigor publicada, 0,7 formalización, 0,4 adjudicación). */
export function confianzaFinTexto(c) {
  if (typeof c !== "number") return "fecha estimada";
  if (c >= 0.85) return "inicio publicado: fecha fiable";
  if (c >= 0.65) return "calculada desde la formalización";
  return "calculada desde la adjudicación: orientativa";
}

/** Qué se sabe de las prórrogas de un contrato, en una línea. */
export function prorrogasTexto(x, conFecha = fechaCivilTexto) {
  if (x.prorrogas_posibles === false) return "Sin prórrogas previstas";
  if (x.prorrogas_posibles === true) return x.fecha_fin_con_prorrogas ? `Con prórrogas podría llegar hasta el ${conFecha(x.fecha_fin_con_prorrogas)}` : "Admite prórrogas (sin fecha calculada)";
  return x.prorrogas_texto ? "Prórrogas: léelo en el pliego (abajo)" : "Prórrogas: no consta";
}

/** Dirección de «contratos que vencen» con el mismo mercado que se está mirando en Competencia. */
export function vencenDeMercado(filtros) {
  const p = new URLSearchParams();
  for (const c of limpiarCpv(filtros.cpv)) p.append("cpv", c);
  for (const c of limpiarNuts(filtros.nuts)) p.append("nuts", c);
  for (const c of limpiarNifs(filtros.comprador)) p.append("comprador", c);
  const q = p.toString();
  return q ? `/licitaciones/vencen?${q}` : "/licitaciones/vencen";
}


// ---- Ficha de organización (GET /organizations/{id} del motor) ----

export const FILTROS_ORG_VACIOS = { desde: "", hasta: "", cpv: "" };
export const ROLES_ORGANIZACION = { comprador: "Comprador", proveedor: "Adjudicataria" };

/** Dirección de la ficha de una organización a partir de su UUID (el de las listas); sin UUID válido no hay enlace. */
export const fichaOrgHref = (id) => (UUID.test(id || "") ? `/licitaciones/organizaciones/${id}` : null);

/** Filtros de la ficha → parámetros de GET /organizations/{id}. */
export function orgAQuery(f) {
  const p = new URLSearchParams();
  const desde = fechaValida(f.desde), hasta = fechaValida(f.hasta);
  if (desde) p.set("desde", desde);
  if (hasta && (!desde || desde <= hasta)) p.set("hasta", hasta);
  for (const c of limpiarCpv(f.cpv)) p.append("cpv", c);
  return p;
}

export function queryAOrg(sp) {
  return { desde: sp.get("desde") || "", hasta: sp.get("hasta") || "", cpv: sp.getAll("cpv").join(" ") };
}

/** «NIF B11111111 · DIR3 L01170000». */
export const identificadoresTexto = (ids) => (ids || []).map((i) => `${i.esquema} ${i.valor}`).join(" · ");

/** «2026-T3» → «3.er trimestre de 2026» (otro texto, tal cual). */
export function trimestreTexto(t) {
  const m = /^(\d{4})-T([1-4])$/.exec(t || "");
  return m ? `T${m[2]} ${m[1]}` : String(t || "—");
}

/** Cuánto se concentra un comprador en un solo adjudicatario (0–1), con la lectura que se le puede dar sin pasarse. */
export function repeticionTexto(r) {
  if (typeof r !== "number" || !Number.isFinite(r) || r < 0 || r > 1) return "";
  const p = `${Math.round(r * 100)} %`;
  return r >= 0.5 ? `${p} de sus contratos van al mismo adjudicatario: mercado muy concentrado` : `${p} de sus contratos van al adjudicatario más frecuente`;
}

/** Altura (0–100) de la barra de un trimestre respecto al mayor de la serie; un trimestre con contratos siempre se ve. */
export function alturasTrimestres(ts) {
  const max = Math.max(0, ...(ts || []).map((t) => t.contratos || 0));
  return (ts || []).map((t) => (max > 0 && t.contratos > 0 ? Math.max(6, Math.round((t.contratos / max) * 100)) : 0));
}

/** Enlace a «Competencia» con un CPV (grupo de 5 cifras) de la ficha. */
export const competenciaDeCpv = (cpv) => (/^\d{2,8}$/.test(cpv || "") ? `/licitaciones/competencia?cpv=${cpv}` : "/licitaciones/competencia");
