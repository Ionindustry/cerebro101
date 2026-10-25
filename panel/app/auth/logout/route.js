import { cookies } from "next/headers";
import { COOKIE, cerrarSesion, urlLogout, urlPanel } from "../../../lib/sesion";

export async function GET() {
  const jar = await cookies();
  const s = await cerrarSesion(jar.get(COOKIE)?.value);
  const destino = process.env.PANEL_USUARIO_DESARROLLO ? urlPanel("/") : urlLogout(s?.idToken);
  const r = new Response(null, { status: 302, headers: { Location: destino } });
  r.headers.append("Set-Cookie", `${COOKIE}=; Path=/; Max-Age=0`);
  return r;
}
