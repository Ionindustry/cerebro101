import { COOKIE_PKCE, nuevoPkce, opcionesCookie, urlLogin } from "../../../lib/sesion";

export async function GET() {
  const pkce = nuevoPkce();
  const r = new Response(null, { status: 302, headers: { Location: urlLogin(pkce) } });
  const c = opcionesCookie(600);
  r.headers.append("Set-Cookie", `${COOKIE_PKCE}=${pkce.estado}.${pkce.verificador}; Path=/; Max-Age=600; HttpOnly; SameSite=Lax${c.secure ? "; Secure" : ""}`);
  return r;
}
