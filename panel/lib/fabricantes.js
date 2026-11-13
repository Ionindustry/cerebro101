// Ranking de fabricantes por sector (GET licitaciones/fabricantes/ranking). Puro.
export const ORDENES = [{ id: "seleccion", nombre: "Selección del documento" }, { id: "ventas", nombre: "Por ventas de seguridad (a&s)" }];

/** Ventas de seguridad en millones de USD → «12.976,6 M USD»; «sin dato» si no hay cifra (no es cero). */
export function ventasTexto(v) {
  if (v === null || v === undefined || v === "") return "sin dato";
  const n = Number(v);
  return Number.isNaN(n) ? "sin dato" : `${n.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} M USD`;
}

/** Estado del dominio de un fabricante para fichas: autorizado, comprobado en el directorio (falta autorizarlo), conocido sin comprobar o desconocido. */
export function estadoDominio(f) {
  if (f.autorizado) return "autorizado";
  if (f.comprobado) return "comprobado: falta autorizar";
  if (f.en_directorio) return "en el directorio, sin comprobar";
  return f.dominio ? "no está en el directorio" : "sin web";
}

/** Comando de Ubuntu para autorizar los dominios comprobados que aún no lo están (vacío si no hay). */
export function comandoAutorizarRanking(sectores) {
  const d = [...new Set((sectores || []).flatMap((s) => s.fabricantes).filter((f) => f.comprobado && !f.autorizado && f.dominio).map((f) => f.dominio))];
  return d.length ? `python3 scripts/fichas_autorizar.py ${d.join(" ")}` : "";
}
