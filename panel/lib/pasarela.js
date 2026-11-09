// Pasarela larga hacia la API: el fetch de Node corta a los 5 minutos si la API no ha empezado a responder («Headers Timeout»), y un agente puede tardar más.
// Aquí se usa el módulo http, que espera lo que haga falta hasta un plazo propio, y cualquier fallo se convierte en un mensaje claro en vez de una respuesta vacía.
import http from "node:http";
import https from "node:https";

export const PLAZO_MS = 30 * 60 * 1000;

export function mensajeFallo(e, plazoMs = PLAZO_MS) {
  if (e && e.code === "PLAZO") return `La API no ha respondido en ${Math.round(plazoMs / 60000)} minutos`;
  if (e && (e.code === "ECONNREFUSED" || e.code === "ENOTFOUND" || e.code === "EAI_AGAIN")) return "No se puede conectar con la API (¿se está reiniciando?)";
  if (e && e.code === "ECONNRESET") return "La API cortó la conexión (¿se ha reiniciado a mitad de la petición?)";
  return "Falló la comunicación con la API";
}

export function enviar(url, { method = "GET", headers = {}, body, plazoMs = PLAZO_MS } = {}) {
  return new Promise((resolver, rechazar) => {
    const u = new URL(url);
    const lib = u.protocol === "https:" ? https : http;
    const cuerpo = body == null || method === "GET" ? null : Buffer.from(body);
    const h = { ...headers };
    if (cuerpo) h["Content-Length"] = cuerpo.length;
    const req = lib.request(u, { method, headers: h }, (res) => {
      const trozos = [];
      res.on("data", (t) => trozos.push(t));
      res.on("end", () => { clearTimeout(reloj); resolver({ status: res.statusCode || 502, texto: Buffer.concat(trozos).toString("utf8") }); });
      res.on("error", (e) => { clearTimeout(reloj); rechazar(e); });
    });
    const reloj = setTimeout(() => { const e = new Error("plazo"); e.code = "PLAZO"; req.destroy(e); }, plazoMs);
    req.on("error", (e) => { clearTimeout(reloj); rechazar(e); });
    if (cuerpo) req.write(cuerpo);
    req.end();
  });
}

// Devuelve siempre {status, texto} con JSON: si la API falla, un 502/504 con «detail» y «codigo» (el panel lo muestra tal cual).
export async function reenviarSeguro(url, opciones = {}) {
  try {
    return await enviar(url, opciones);
  } catch (e) {
    const plazo = e && e.code === "PLAZO";
    return { status: plazo ? 504 : 502, texto: JSON.stringify({ detail: mensajeFallo(e, opciones.plazoMs), codigo: "pasarela" }) };
  }
}
