import { cookies } from "next/headers";
import { COOKIE, modoDesarrollo, obtenerSesion } from "../../../lib/sesion";

export async function GET() {
  if (modoDesarrollo()) return Response.json({ usuario: process.env.PANEL_USUARIO_DESARROLLO, desarrollo: true });
  const s = await obtenerSesion((await cookies()).get(COOKIE)?.value);
  if (!s) return Response.json({ error: "sin sesión" }, { status: 401 });
  return Response.json({ usuario: s.usuario, roles: s.roles, grupos: s.grupos });
}
