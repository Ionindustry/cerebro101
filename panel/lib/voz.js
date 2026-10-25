// Respuesta de Jarvis por voz: limpiar el texto antes de leerlo, elegir idioma y explicar los fallos. Sin dependencias: se prueba con node --test.

// Lo que se lee en alto no puede llevar marcas de formato, enlaces ni código: se dicen mal o no se dicen
export function limpiarParaHablar(texto = "") {
  return String(texto)
    .replace(/```[\s\S]*?```/g, " ")                    // bloques de código
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")               // imágenes
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")             // [texto](enlace) → texto
    .replace(/https?:\/\/\S+/g, " ")                     // direcciones sueltas
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")                  // títulos
    .replace(/^\s*[-*•]\s+/gm, "")                       // viñetas
    .replace(/^\s*>\s?/gm, "")
    .replace(/[*_~]{1,3}([^*_~\n]+)[*_~]{1,3}/g, "$1")   // negrita y cursiva
    .replace(/\s*\n\s*/g, ". ").replace(/\.\s*\./g, ".")
    .replace(/\s+/g, " ")
    .trim();
}

// Una respuesta larguísima no se lee entera: se corta en el final de una frase
export function recortarParaHablar(texto, max = 900) {
  if (texto.length <= max) return texto;
  const corte = texto.slice(0, max);
  const fin = Math.max(corte.lastIndexOf(". "), corte.lastIndexOf("? "), corte.lastIndexOf("! "));
  return (fin > max * 0.5 ? corte.slice(0, fin + 1) : corte).trim();
}

const CATALAN = /\b(és|això|què|amb|però|també|molt|gràcies|perquè|vostè|aquest|aquesta|hi ha|bon dia|ens|nosaltres|vull|puc|fer)\b|l·l|ny\b/gi;

// La voz se elige por idioma: catalán si el texto lo parece (varias marcas propias), castellano en otro caso
export function detectarIdioma(texto = "") {
  return (texto.match(CATALAN) || []).length >= 2 ? "ca" : "es";
}

export function mensajeErrorVoz(estado, detalle = "") {
  if (estado === 503) return detalle || "Falta la voz de Jarvis en el servidor: python3 scripts/voces_descargar.py y docker compose restart voz.";
  if (estado === 401) return "La sesión ha caducado. Recarga la página.";
  if (estado === 0) return "No he podido contactar con el servicio de voz.";
  return detalle || `La voz ha fallado (error ${estado}).`;
}

export const mensajeAudioBloqueado = "El navegador ha bloqueado el audio. Pulsa cualquier sitio de la página y vuelve a probar, o desactiva y activa «Respuesta por voz».";
