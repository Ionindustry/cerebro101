// Pasarela del panel a la API del Cerebro.
// Reenvía cada petición con el token de la sesión de Keycloak (en desarrollo, con cabeceras de prueba).
import { cookies } from "next/headers";
import { COOKIE, obtenerSesion } from "../../../lib/sesion";

const API = process.env.CEREBRO_API || "http://localhost:8000";

async function cabeceras() {
  const h = { "Content-Type": "application/json" };
  if (process.env.PANEL_USUARIO_DESARROLLO) {
    h["X-Usuario"] = process.env.PANEL_USUARIO_DESARROLLO;
    h["X-Roles"] = process.env.PANEL_ROLES_DESARROLLO || "direccion,responsable";
    h["X-Departamentos"] = process.env.PANEL_DEPARTAMENTOS_DESARROLLO || "";
    return h;
  }
  const s = await obtenerSesion((await cookies()).get(COOKIE)?.value);
  if (!s) return null;
  h.Authorization = `Bearer ${s.acceso}`;
  return h;
}

async function reenviar(req, { params }) {
  const { ruta } = await params;
  const h = await cabeceras();
  if (!h) return Response.json({ error: "Sesión caducada" }, { status: 401 });
  const url = `${API}/${ruta.join("/")}${new URL(req.url).search}`;
  const r = await fetch(url, {
    method: req.method,
    headers: h,
    body: req.method === "GET" ? undefined : await req.text(),
  });
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}

export { reenviar as GET, reenviar as POST };
