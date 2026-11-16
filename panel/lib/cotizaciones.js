// Cotizaciones a proveedores (GET/POST cotizaciones…). Puro, para poder probarlo.
export const ESTADO_COTIZACION = { borrador: "Borrador", enviada: "Enviada", respondida: "Respondida", cancelada: "Cancelada" };
export const MODO_COTIZACION = { enviar: "La envía el sistema cuando Dirección confirma", manual: "La mando yo" };
export const ETIQUETA_ERP = { creada: "Creada en el ERP", sin_articulo: "El artículo no está en el ERP", sin_proveedor: "El proveedor no está en el ERP", error: "El ERP no la ha aceptado", desactivada: "ERP desactivado" };
export const claseCotizacion = (c) => (c.estado === "respondida" ? "abierta" : c.estado === "cancelada" ? "anulada" : c.sin_respuesta ? "aviso" : "");

/** «DS-2CD… × 12 · A-Secur · 15 días». */
export const resumenCotizacion = (c) => `${c.referencia} × ${c.cantidad} · ${c.proveedor} · plazo ${c.plazo}`;

/** El correo ya redactado como enlace «mailto:» para abrirlo en el programa de correo (modo manual). Solo lleva lo que ya lleva el correo. */
export function mailtoHref(c) {
  return `mailto:${encodeURIComponent(c.email).replace("%40", "@")}?subject=${encodeURIComponent(c.asunto)}&body=${encodeURIComponent(c.cuerpo)}`;
}

const entero = (t) => (/^\d{1,6}$/.test(String(t ?? "").trim()) ? Number(String(t).trim()) : null);

/** El formulario de nueva cotización → cuerpo a enviar; o un mensaje claro. El servidor vuelve a comprobarlo todo. */
export function cotizacionAEnvio(f) {
  const referencia = String(f.referencia || "").trim().replace(/\s+/g, " ");
  if (referencia.length < 2) return { error: "Escribe la referencia." };
  const cantidad = entero(f.cantidad);
  if (!cantidad || cantidad < 1) return { error: "La cantidad tiene que ser un número entero mayor que cero." };
  const tipo = f.plazo_tipo === "fecha" ? "fecha" : "dias";
  const valor = String(f.plazo_valor || "").trim();
  if (tipo === "dias" && !(entero(valor) >= 1)) return { error: "Los días de plazo tienen que ser un número entero mayor que cero." };
  if (tipo === "fecha" && !/^\d{4}-\d{2}-\d{2}$/.test(valor)) return { error: "La fecha de entrega tiene que ser AAAA-MM-DD." };
  if (String(f.proveedor || "").trim().length < 2) return { error: "Elige el proveedor." };
  if (!["enviar", "manual"].includes(f.modo)) return { error: "Elige cómo se envía: lo envía el sistema o lo mandas tú." };
  const c = { referencia, cantidad, plazo_tipo: tipo, plazo_valor: tipo === "dias" ? entero(valor) : valor, proveedor: String(f.proveedor).trim(), modo: f.modo };
  if (String(f.marca || "").trim()) c.marca = String(f.marca).trim();
  if (f.licitacion) c.licitacion = String(f.licitacion);
  if (f.partida) c.partida = Number(f.partida) || undefined;
  return { cuerpo: c };
}

/** El formulario de respuesta del proveedor → cuerpo a enviar; o un mensaje claro. */
export function respuestaAEnvio(f) {
  const precio = String(f.precio || "").trim().replace(",", ".");
  if (!/^\d+(\.\d{1,4})?$/.test(precio) || Number(precio) <= 0) return { error: "El precio unitario tiene que ser mayor que cero (como mucho 4 decimales)." };
  const c = { precio, moneda: ["EUR", "USD", "GBP"].includes(f.moneda) ? f.moneda : "EUR", nota: String(f.nota || "").trim().slice(0, 500) };
  if (String(f.plazo_dias || "").trim()) { const n = entero(f.plazo_dias); if (n === null || n > 730) return { error: "El plazo del proveedor son días (0 a 730)." }; c.plazo_dias = n; }
  if (String(f.validez_hasta || "").trim()) { if (!/^\d{4}-\d{2}-\d{2}$/.test(String(f.validez_hasta).trim())) return { error: "La validez de la oferta es una fecha AAAA-MM-DD." }; c.validez_hasta = String(f.validez_hasta).trim(); }
  return { cuerpo: c };
}

/** «12,50 EUR · entrega en 7 días · válida hasta 2026-12-31». */
export function respuestaTexto(r) {
  if (!r?.precio) return "";
  return [`${Number(r.precio).toLocaleString("es-ES", { maximumFractionDigits: 4 })} ${r.moneda}`, r.plazo_dias !== undefined && r.plazo_dias !== null ? `entrega en ${r.plazo_dias} días` : null, r.validez_hasta ? `válida hasta ${r.validez_hasta}` : null].filter(Boolean).join(" · ");
}

export function mensajeCotizaciones(status, detalle = "") {
  if (status === 403) return detalle || "Solo Dirección y Licitaciones ven las cotizaciones (y solo Dirección envía).";
  if ((status === 422 || status === 404) && detalle) return detalle;
  return "No se ha podido completar la operación. Inténtalo de nuevo más tarde.";
}

/** De un producto escrito en texto libre («Cámara domo Milesight MS-C8573-FPB 4MP»), la referencia que se le pide al proveedor: la palabra con letras y números más larga (mín. 4 caracteres); si no hay, el texto recortado. */
export function referenciaDeProducto(texto) {
  const palabras = String(texto || "").split(/\s+/).map((p) => p.replace(/^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$/g, "")).filter((p) => p.length >= 4 && /[A-Za-z]/.test(p) && /\d/.test(p) && /^[A-Za-z0-9._/+()#:-]+$/.test(p));
  if (palabras.length) return palabras.sort((a, b) => b.length - a.length)[0].slice(0, 80);
  return String(texto || "").trim().replace(/\s+/g, " ").slice(0, 80);
}
