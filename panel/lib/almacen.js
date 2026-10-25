// Dónde viven las sesiones del panel. Con REDIS_PANEL_URL (producción) en un Redis propio del panel, con contraseña,
// cifradas (AES-256-GCM) y con la cookie hasheada como clave: ni un volcado de Redis ni la API sirven para suplantar a nadie.
// Sin esa variable (desarrollo) se guardan en memoria y se pierden al reiniciar el panel.
import crypto from "node:crypto";
import net from "node:net";

const memoria = (globalThis.__cerebroSesiones ??= new Map());
const URL_REDIS = () => process.env.REDIS_PANEL_URL || "";
const TIEMPO_MAX = 2000;

/** Cliente RESP mínimo (una conexión por orden: pocas órdenes por petición y sin dependencias). */
export function ordenRedis(urlTexto, args) {
  const u = new URL(urlTexto);
  const cuerpo = (a) => `*${a.length}\r\n` + a.map((x) => { const b = Buffer.from(String(x)); return `$${b.length}\r\n${b.toString("latin1")}\r\n`; }).join("");
  const ordenes = [];
  if (u.password) ordenes.push(["AUTH", ...(u.username ? [decodeURIComponent(u.username)] : []), decodeURIComponent(u.password)]);
  ordenes.push(args);
  return new Promise((resolve, reject) => {
    const s = net.connect({ host: u.hostname, port: Number(u.port || 6379) });
    let buf = Buffer.alloc(0);
    const respuestas = [];
    const fin = (err, val) => { clearTimeout(t); s.destroy(); err ? reject(err) : resolve(val); };
    const t = setTimeout(() => fin(new Error("Redis no responde")), TIEMPO_MAX);
    s.on("error", fin);
    s.on("connect", () => s.write(Buffer.from(ordenes.map(cuerpo).join(""), "latin1")));
    s.on("data", (d) => {
      buf = Buffer.concat([buf, d]);
      for (;;) {
        const r = leer(buf);
        if (!r) return;
        buf = buf.subarray(r.usado);
        if (r.error) return fin(new Error(`Redis: ${r.error}`));
        respuestas.push(r.valor);
        if (respuestas.length === ordenes.length) return fin(null, respuestas.at(-1));
      }
    });
  });
}

function leer(b) {   // una respuesta RESP completa o null si faltan datos
  const fin = b.indexOf("\r\n");
  if (fin < 0) return null;
  const tipo = String.fromCharCode(b[0]);
  const linea = b.subarray(1, fin).toString();
  const sig = fin + 2;
  if (tipo === "+") return { valor: linea, usado: sig };
  if (tipo === "-") return { error: linea, usado: sig };
  if (tipo === ":") return { valor: Number(linea), usado: sig };
  if (tipo === "$") {
    const n = Number(linea);
    if (n < 0) return { valor: null, usado: sig };
    if (b.length < sig + n + 2) return null;
    return { valor: b.subarray(sig, sig + n).toString("latin1"), usado: sig + n + 2 };
  }
  return { error: `respuesta no esperada ${tipo}`, usado: b.length };
}

const clave = () => {
  const c = process.env.PANEL_SESION_SECRET;
  if (!c) throw new Error("Falta PANEL_SESION_SECRET para guardar las sesiones en Redis");
  return crypto.createHash("sha256").update(c).digest();
};
const llave = (id) => "sesion:" + crypto.createHash("sha256").update(id).digest("hex");

export function cifrar(obj) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv("aes-256-gcm", clave(), iv);
  const datos = Buffer.concat([c.update(JSON.stringify(obj), "utf8"), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), datos]).toString("base64url");
}

export function descifrar(texto) {
  const b = Buffer.from(texto, "base64url");
  const d = crypto.createDecipheriv("aes-256-gcm", clave(), b.subarray(0, 12));
  d.setAuthTag(b.subarray(12, 28));
  return JSON.parse(Buffer.concat([d.update(b.subarray(28)), d.final()]).toString("utf8"));
}

export const conRedis = () => Boolean(URL_REDIS());

export async function leerSesion(id) {
  if (!conRedis()) return memoria.get(id) || null;
  const v = await ordenRedis(URL_REDIS(), ["GET", llave(id)]);
  if (!v) return null;
  try { return descifrar(v); } catch { return null; }      // valor manipulado o clave cambiada: sin sesión
}

export async function guardarSesion(id, sesion, segundos) {
  if (!conRedis()) { memoria.set(id, sesion); return; }
  await ordenRedis(URL_REDIS(), ["SET", llave(id), cifrar(sesion), "EX", Math.max(1, Math.floor(segundos))]);
}

export async function borrarSesion(id) {
  if (!conRedis()) { memoria.delete(id); return; }
  await ordenRedis(URL_REDIS(), ["DEL", llave(id)]);
}

/** Solo una petición renueva el token a la vez (Keycloak invalida el refresh anterior). true si se obtuvo el turno. */
export async function tomarTurno(id, ms = 10000) {
  if (!conRedis()) return true;
  return (await ordenRedis(URL_REDIS(), ["SET", llave(id) + ":turno", "1", "NX", "PX", ms])) === "OK";
}
export async function soltarTurno(id) {
  if (conRedis()) await ordenRedis(URL_REDIS(), ["DEL", llave(id) + ":turno"]).catch(() => {});
}
