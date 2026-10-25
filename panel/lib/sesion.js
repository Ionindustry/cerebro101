// Sesión del panel con Keycloak (OIDC, código de autorización + PKCE, cliente público).
// El navegador solo guarda un identificador opaco (cookie httpOnly); los tokens viven en el servidor del panel:
// en Redis (cifrados, ver almacen.js) si hay REDIS_PANEL_URL, de modo que sobreviven a reiniciar el panel y sirven con varias
// réplicas; en memoria en desarrollo.
import crypto from "node:crypto";
import { borrarSesion, guardarSesion, leerSesion, soltarTurno, tomarTurno } from "./almacen";

const PUBLICA = process.env.KEYCLOAK_URL_PUBLICA || "http://localhost:8080";   // la que ve el navegador
const INTERNA = process.env.KEYCLOAK_URL_INTERNA || PUBLICA;                  // la que usa el servidor del panel
const REALM = process.env.KEYCLOAK_REALM || "cerebro";
const CLIENTE = process.env.KEYCLOAK_CLIENTE || "cerebro-panel";
const PANEL = (process.env.PANEL_URL || "http://localhost:3000").replace(/\/$/, "");

export const COOKIE = "cerebro_sesion";
export const COOKIE_PKCE = "cerebro_pkce";
export const modoDesarrollo = () => Boolean(process.env.PANEL_USUARIO_DESARROLLO);
export const urlPanel = (ruta = "") => PANEL + ruta;

const base = (url) => `${url}/realms/${REALM}/protocol/openid-connect`;

export function opcionesCookie(maxAge) {
  return { httpOnly: true, sameSite: "lax", secure: PANEL.startsWith("https"), path: "/", maxAge };
}

const b64 = (b) => b.toString("base64url");

export function nuevoPkce() {
  const verificador = b64(crypto.randomBytes(32));
  return { verificador, desafio: b64(crypto.createHash("sha256").update(verificador).digest()), estado: b64(crypto.randomBytes(16)) };
}

export function urlLogin({ desafio, estado }) {
  const p = new URLSearchParams({
    client_id: CLIENTE, response_type: "code", scope: "openid", redirect_uri: urlPanel("/auth/callback"),
    state: estado, code_challenge: desafio, code_challenge_method: "S256",
  });
  return `${base(PUBLICA)}/auth?${p}`;
}

export const urlLogout = (idToken) =>
  `${base(PUBLICA)}/logout?` + new URLSearchParams({
    post_logout_redirect_uri: urlPanel("/"), client_id: CLIENTE, ...(idToken ? { id_token_hint: idToken } : {}),
  });

async function pedirTokens(cuerpo) {
  const r = await fetch(`${base(INTERNA)}/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CLIENTE, ...cuerpo }),
  });
  if (!r.ok) throw new Error(`Keycloak ${r.status}`);
  return r.json();
}

export const canjearCodigo = (code, verificador) =>
  pedirTokens({ grant_type: "authorization_code", code, code_verifier: verificador, redirect_uri: urlPanel("/auth/callback") });

export function claims(token) {
  try { return JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString()); } catch { return {}; }
}

async function guardar(id, t) {
  const c = claims(t.access_token);
  const caducaRefresco = Date.now() + (t.refresh_expires_in || 1800) * 1000;
  const sesion = {
    acceso: t.access_token, refresco: t.refresh_token, idToken: t.id_token,
    caduca: (c.exp || 0) * 1000, caducaRefresco,
    usuario: c.preferred_username || c.sub, roles: c.realm_access?.roles || [], grupos: c.groups || [],
  };
  await guardarSesion(id, sesion, (caducaRefresco - Date.now()) / 1000);
  return sesion;
}

export async function crearSesion(tokens) {
  const id = b64(crypto.randomBytes(32));
  await guardar(id, tokens);
  return id;
}

export async function cerrarSesion(id) {
  if (!id) return null;
  const s = await leerSesion(id).catch(() => null);
  await borrarSesion(id).catch(() => {});
  return s;
}

/** Devuelve la sesión con un token de acceso vigente (lo renueva si le queda poco), o null. Si el almacén falla: sin sesión. */
export async function obtenerSesion(id) {
  if (!id) return null;
  try {
    let s = await leerSesion(id);
    if (!s) return null;
    if (s.caduca - Date.now() > 30_000) return s;
    if (!s.refresco || s.caducaRefresco < Date.now()) { await borrarSesion(id); return null; }
    if (!(await tomarTurno(id))) {                       // otra petición (u otra réplica) la está renovando: esperar y releer
      await new Promise((r) => setTimeout(r, 400));
      s = await leerSesion(id);
      return s && s.caduca - Date.now() > 0 ? s : null;
    }
    try {
      return await guardar(id, await pedirTokens({ grant_type: "refresh_token", refresh_token: s.refresco }));
    } catch {
      await borrarSesion(id);
      return null;
    } finally {
      await soltarTurno(id);
    }
  } catch {
    return null;
  }
}
