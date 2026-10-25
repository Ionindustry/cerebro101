// Elección del micrófono de Jarvis (el de una webcam USB, el del portátil, un auricular…). Sin dependencias del navegador: se prueba con node --test.

// Solo las entradas de audio; el navegador a veces repite el «predeterminado» y el «comunicaciones» de Windows con otro id
export const soloEntradas = (dispositivos = []) =>
  dispositivos.filter((d) => d.kind === "audioinput" && d.deviceId !== "communications");

// Sin permiso del navegador las etiquetas vienen vacías: se numeran para que la lista no esté en blanco
export const nombre = (d, i) => d.label || `Micrófono ${i + 1}`;

// Se respeta la elección guardada si ese micrófono sigue conectado; si no, el predeterminado del sistema
export function elegir(dispositivos, guardado) {
  const lista = soloEntradas(dispositivos);
  if (guardado && lista.some((d) => d.deviceId === guardado)) return guardado;
  return lista.find((d) => d.deviceId === "default")?.deviceId ?? lista[0]?.deviceId ?? "";
}

// «exact» obliga a usar justo ese micrófono; con el predeterminado no se pide ninguno concreto
export const restricciones = (id) => ({ audio: id && id !== "default" ? { deviceId: { exact: id } } : true });

export function mensajeError(e) {
  const n = e?.name;
  if (n === "NotAllowedError" || n === "SecurityError")
    return "El navegador no deja usar el micrófono. Pulsa el candado de la barra de direcciones, permite el micrófono y vuelve a intentarlo.";
  if (n === "NotFoundError" || n === "OverconstrainedError")
    return "No encuentro ese micrófono. Comprueba que la cámara está conectada y elígelo de nuevo en la lista.";
  if (n === "NotReadableError")
    return "Otro programa está usando ese micrófono (Teams, Zoom…). Ciérralo o elige otro micrófono.";
  return "No se ha podido abrir el micrófono.";
}

// Nivel de 0 a 1 a partir de las muestras del analizador (0–255, silencio en 128): sirve para ver que el micrófono recoge sonido
export function nivel(muestras) {
  if (!muestras?.length) return 0;
  let max = 0;
  for (const v of muestras) max = Math.max(max, Math.abs(v - 128));
  return Math.min(1, max / 64);
}

// Qué decirle a la persona según lo que ha pasado al transcribir: `estado` es el código HTTP, 0 si ni siquiera se pudo llegar al servicio
export function mensajeTranscripcion(estado, texto = "") {
  if (estado === 200) return texto.trim() ? "" : "No he oído palabras. Habla más cerca del micrófono, sube su volumen o prueba con otro micrófono de la lista.";
  if (estado === 401) return "La sesión ha caducado. Recarga la página e inicia sesión de nuevo.";
  return "El servicio de voz del servidor no responde" + (estado ? ` (error ${estado})` : "") + ". El micrófono funciona, pero hay que revisar el servicio de voz: docker compose logs voz.";
}
