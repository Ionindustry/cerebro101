// Documentos que se adjuntan al chat de Jarvis (POST /cerebro/documentos/subir, api/cerebro/subidas.py): comprobaciones previas en el navegador y textos para la persona.
// La comprobación de verdad (por el contenido, antivirus, tamaño) la hace siempre la API; esto solo evita subir lo que se va a rechazar.

export const MAX_MB = 25;
export const EXTENSIONES = [".pdf", ".docx", ".xlsx", ".odt", ".ods", ".csv", ".tsv", ".txt"];
export const ACCEPT = EXTENSIONES.join(",");

/** null si el fichero puede subirse; si no, el motivo en una frase. */
export function validarAdjunto(f) {
  if (!f || !f.name) return "No se ha podido leer el fichero";
  const nombre = String(f.name).toLowerCase();
  if (nombre.endsWith(".xls") || nombre.endsWith(".doc")) return "Es un formato de Office antiguo: guárdalo como .xlsx, .docx o CSV y vuelve a subirlo";
  if (!EXTENSIONES.some((e) => nombre.endsWith(e))) return "Formato no admitido. Sube un PDF, Word, Excel (.xlsx), OpenDocument, CSV o texto";
  if (!f.size) return "El fichero está vacío";
  if (f.size > MAX_MB * 1_000_000) return `El fichero pesa más de ${MAX_MB} MB`;
  return null;
}

/** Los bytes de un fichero en base64 (por trozos: un `String.fromCharCode(...todo)` revienta con ficheros grandes). */
export function aBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binario = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binario += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(binario);
}

/** Lo que la persona lee cuando la subida falla. `detalle` es el mensaje de la API cuando es texto. */
export function mensajeSubida(status, detalle = "") {
  if (status === 413) return detalle || `El fichero pesa más de ${MAX_MB} MB`;
  if (status === 422 && detalle) return detalle;
  if (status === 401 || status === 403) return "Tu sesión ha caducado: vuelve a entrar.";
  return "No se ha podido subir el documento. Inténtalo de nuevo más tarde.";
}

/** Una frase con el estado de un documento ya subido. */
export function estadoAdjuntoTexto(a) {
  if (!a) return "";
  if (a.disponible) return `${a.paginas} ${a.unidad === "hoja" ? "hoja" : a.unidad === "bloque" ? "bloque" : "página"}${a.paginas === 1 ? "" : "s"}`;
  if (a.estado === "infectado") return "descartado por el antivirus";
  if (a.estado === "no_analizable") return a.motivo || "no se ha podido analizar";
  return a.aviso || a.motivo || "no se ha podido leer";
}

/** Los ids que se mandan con el mensaje: solo los documentos disponibles, sin repetir y como mucho 5. */
export function idsParaMensaje(adjuntos) {
  return [...new Set((adjuntos || []).filter((a) => a && a.disponible).map((a) => a.id))].slice(0, 5);
}

/** El texto de la burbuja de la persona: lo que escribió y, debajo, los nombres de lo que adjuntó. */
export function textoConAdjuntos(texto, adjuntos) {
  const n = (adjuntos || []).filter((a) => a && a.disponible).map((a) => `📎 ${a.nombre}`);
  return n.length ? `${texto}\n${n.join("\n")}` : texto;
}
