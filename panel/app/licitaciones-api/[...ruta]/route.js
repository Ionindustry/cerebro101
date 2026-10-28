// Pasarela del panel a la API del motor de licitaciones (ADR 0007 §4). El navegador nunca habla con el motor: esta ruta, en el servidor,
//   1. exige sesión y comprueba que el usuario tenga acceso a Licitaciones (grupo del departamento, dirección o servicio),
//   2. deja pasar solo lecturas de lo que el motor sirve (lib/licitaciones.js: lista blanca por ruta y método),
//   3. añade la credencial del motor, que no sale nunca hacia el navegador, y limita el tiempo de espera.
import { cookies } from "next/headers";
import { COOKIE, obtenerSesion } from "../../../lib/sesion";
import { decidir } from "../../../lib/licitaciones";

const API = (process.env.LICITACIONES_API_URL || "http://licitaciones-api:8080").replace(/\/$/, "") + "/api/v1";
const TOKEN = process.env.LICITACIONES_API_TOKEN || "";
const PLAZO_MS = 5000;

async function identidad() {
  if (process.env.PANEL_USUARIO_DESARROLLO) {
    const lista = (v) => (v || "").split(",").map((x) => x.trim()).filter(Boolean);
    return {
      usuario: process.env.PANEL_USUARIO_DESARROLLO,
      roles: lista(process.env.PANEL_ROLES_DESARROLLO || "direccion,responsable"),
      grupos: lista(process.env.PANEL_DEPARTAMENTOS_DESARROLLO),
    };
  }
  const s = await obtenerSesion((await cookies()).get(COOKIE)?.value);
  return s ? { usuario: s.usuario, roles: s.roles || [], grupos: s.grupos || [] } : null;
}

const problema = (status, codigo, detalle) =>
  new Response(JSON.stringify({ type: `https://licitaciones.101.cat/errores/${codigo}`, title: detalle, status, codigo, detail: detalle }), {
    status, headers: { "Content-Type": "application/problem+json", "Cache-Control": "no-store" },
  });

async function reenviar(req, { params }) {
  const { ruta } = await params;
  const id = await identidad();
  const rechazo = decidir({ metodo: req.method, segmentos: ruta, identidad: id, hayCredencial: Boolean(TOKEN) });
  if (rechazo) return problema(rechazo.status, rechazo.codigo, rechazo.detalle);

  const cabeceras = { Authorization: `Bearer ${TOKEN}`, "X-Usuario": id.usuario || "" };
  const etag = req.headers.get("if-none-match");
  if (etag) cabeceras["If-None-Match"] = etag;
  let r;
  try {
    r = await fetch(`${API}/${ruta.join("/")}${new URL(req.url).search}`, { method: "GET", headers: cabeceras, signal: AbortSignal.timeout(PLAZO_MS), cache: "no-store" });
  } catch (e) {
    return e?.name === "TimeoutError" ? problema(504, "no_disponible", "El motor de licitaciones tarda demasiado en responder")
      : problema(503, "no_disponible", "El motor de licitaciones no está disponible");
  }
  // Un 401 del motor es un problema de configuración del panel, no una sesión caducada: no se confunde con la del usuario.
  if (r.status === 401 || r.status === 403) return problema(503, "no_disponible", "El panel no tiene acceso al motor de licitaciones");
  const h = { "Content-Type": r.headers.get("content-type") || "application/json", "Cache-Control": "no-store" };
  if (r.headers.get("etag")) h.ETag = r.headers.get("etag");
  return new Response(r.status === 304 ? null : await r.text(), { status: r.status, headers: h });
}

export { reenviar as GET };
