// Pantalla «Precios»: revisión y aprobación de las propuestas de precios de venta (solo Dirección). Todo lo que calcula es del servidor; aquí solo se formatea y se valida lo que se escribe.

export const CAMBIO_ETIQUETA = { nuevo: "Nuevo", sube: "Sube", baja: "Baja", igual: "Sin cambios" };
export const ESTADO_PROPUESTA = { propuesta: "Pendiente de revisar", aplicando: "Aplicándose…", aplicada: "Aplicada en el ERP", error: "Con error (se puede repetir)", descartada: "Descartada" };

/** «199,5» / «199.50» → 199.5; null si no es un precio válido (positivo, como mucho 2 decimales). Pura. */
export function precioAEnvio(texto) {
  const t = String(texto ?? "").trim().replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(t)) return null;
  const n = Number(t);
  return n > 0 ? n : null;
}

/** «50,0 %» a partir de un margen en fracción («0.5000»). Pura. */
export function margenTexto(m) {
  const n = Number(m);
  return m === null || m === undefined || Number.isNaN(n) ? "—" : `${(n * 100).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

/** «1.234,56 €». Pura. */
export function euros(v) {
  const n = Number(v);
  return v === null || v === undefined || v === "" || Number.isNaN(n) ? "—" : `${n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

/** Resumen de una propuesta en una línea («120 artículos · 30 nuevos · 12 suben · 5 bajan · 3 ajustados»). Pura. */
export function resumenPropuestaTexto(r) {
  if (!r || r.incluidos === undefined) return "";
  const p = [`${r.incluidos} artículos`];
  if (r.nuevo) p.push(`${r.nuevo} nuevos`);
  if (r.sube) p.push(`${r.sube} suben`);
  if (r.baja) p.push(`${r.baja} bajan`);
  if (r.ajustados) p.push(`${r.ajustados} ajustados a mano`);
  if (r.bajo_minimo) p.push(`${r.bajo_minimo} bajo el margen mínimo`);
  return p.join(" · ");
}

/** La consulta de la pantalla a la dirección de la API (solo lo que tiene valor). Pura. */
export function consultaLineas(f, pagina) {
  const q = new URLSearchParams();
  if (f?.familia) q.set("familia", f.familia);
  if (f?.cambio) q.set("cambio", f.cambio);
  if (f?.texto) q.set("q", f.texto);
  if (f?.bajoMinimo) q.set("bajo_minimo", "true");
  if (pagina > 1) q.set("pagina", String(pagina));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const MENSAJE_APLICAR = "Vas a escribir estos precios de venta en el ERP. Es una acción que sale de la empresa y queda registrada a tu nombre. ¿Aplicar?";
