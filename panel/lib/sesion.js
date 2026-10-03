// Sesión del panel con Keycloak (OIDC, código de autorización + PKCE, cliente público).
// El navegador solo guarda un identificador opaco (cookie httpOnly); los tokens viven en el servidor
// del panel. Si el panel se reinicia, las sesiones se pierden y hay que volver a entrar.
import crypto from "node:crypto";

const PUBLICA = process.env.KEYCLOAK_URL_PUBLICA || "http://localhost:8080";   // la que ve el navegador
const INTERNA = process.env.KEYCLOAK_URL_INTERNA || PUBLICA;                  // la que usa el servidor del panel
const REALM = process.env.KEYCLOAK_REALM || "cerebro";
const CLIENTE = process.env.KEYCLOAK_CLIENTE || "cerebro-panel";
const PANEL = (process.env.PANEL_URL || "http://localhost:3000").replace(/\/$/, "");

export const COOKIE = "cerebro_sesion";
export const COOKIE_PKCE = "cerebro_pkce";
export const modoDesarrollo = () => Boolean(process.env.PANEL_USUARIO_DESARROLLO);
export const urlPanel = (ruta = "") => PANEL + ruta;

const sesiones = (globalThis.__cerebroSesiones ??= new Map());
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

function guardar(id, t) {
  const c = claims(t.access_token);
  sesiones.set(id, {
    acceso: t.access_token, refresco: t.refresh_token, idToken: t.id_token,
    caduca: (c.exp || 0) * 1000, caducaRefresco: Date.now() + (t.refresh_expires_in || 1800) * 1000,
    usuario: c.preferred_username || c.sub, roles: c.realm_access?.roles || [], grupos: c.groups || [],
  });
}

export function crearSesion(tokens) {
  const id = b64(crypto.randomBytes(32));
  guardar(id, tokens);
  return id;
}

export const cerrarSesion = (id) => { const s = sesiones.get(id); sesiones.delete(id); return s; };

/** Devuelve la sesión con un token de acceso vigente (lo renueva si le queda poco), o null. */
export async function obtenerSesion(id) {
  const s = id && sesiones.get(id);
  if (!s) return null;
  if (s.caduca - Date.now() > 30_000) return s;
  if (!s.refresco || s.caducaRefresco < Date.now()) { sesiones.delete(id); return null; }
  try {
    guardar(id, await pedirTokens({ grant_type: "refresh_token", refresh_token: s.refresco }));
    return sesiones.get(id);
  } catch {
    sesiones.delete(id);
    return null;
  }
}
