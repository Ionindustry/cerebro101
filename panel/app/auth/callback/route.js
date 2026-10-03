import { cookies } from "next/headers";
import { COOKIE, COOKIE_PKCE, canjearCodigo, crearSesion, opcionesCookie, urlPanel } from "../../../lib/sesion";

export async function GET(req) {
  const q = new URL(req.url).searchParams;
  const jar = await cookies();
  const [estado, verificador] = (jar.get(COOKIE_PKCE)?.value || "").split(".");
  if (q.get("error") || !q.get("code") || !estado || q.get("state") !== estado) {
    return new Response("Inicio de sesión no válido. Vuelve a intentarlo.", { status: 400 });
  }
  let tokens;
  try { tokens = await canjearCodigo(q.get("code"), verificador); }
  catch { return new Response("Keycloak no ha aceptado el inicio de sesión.", { status: 502 }); }
  const r = new Response(null, { status: 302, headers: { Location: urlPanel("/") } });
  const o = opcionesCookie(8 * 3600);
  r.headers.append("Set-Cookie", `${COOKIE}=${crearSesion(tokens)}; Path=/; Max-Age=${o.maxAge}; HttpOnly; SameSite=Lax${o.secure ? "; Secure" : ""}`);
  r.headers.append("Set-Cookie", `${COOKIE_PKCE}=; Path=/; Max-Age=0`);
  return r;
}
