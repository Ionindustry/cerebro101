// «Proveedores y marcas» (GET precios/proveedores-marcas): qué marcas distribuye cada proveedor. Puro, para poder probarlo.

/** «Tarifa», «A mano» o «Tarifa y a mano». */
export function fuenteTexto(fuentes) {
  const f = Array.isArray(fuentes) ? fuentes : [];
  const t = f.includes("tarifa"), m = f.includes("manual");
  return t && m ? "Tarifa y a mano" : m ? "A mano" : t ? "Tarifa" : "—";
}

/** «HIKVISION PRO (529) · HIKVISION PRO NO CCTV (297)»: cómo la escribe la tarifa; vacío si no hay variantes. */
export function variantesTexto(v) {
  return Object.entries(v || {}).map(([k, n]) => `${k} (${n})`).join(" · ");
}

/** Línea de un proveedor: «A-Secur · 29 marcas · 3.265 artículos». */
export function resumenProveedor(p) {
  const n = p?.marcas?.length || 0;
  return `${p?.proveedor || "—"} · ${n} ${n === 1 ? "marca" : "marcas"} · ${new Intl.NumberFormat("es-ES").format(p?.articulos || 0)} artículos`;
}

/** Línea de una marca: «Hikvision · 1.112 artículos · Tarifa». Las manuales no traen artículos. */
export function resumenMarca(m) {
  const a = m?.articulos > 0 ? ` · ${new Intl.NumberFormat("es-ES").format(m.articulos)} artículos` : "";
  return `${m?.marca}${a} · ${fuenteTexto(m?.fuentes)}`;
}

export function mensajeMarcas(status, detalle = "") {
  if (status === 403) return "Los proveedores y sus marcas los ve solo Dirección.";
  if (status === 422 && detalle) return detalle;
  return "No se han podido leer las marcas de los proveedores. Inténtalo de nuevo más tarde.";
}
