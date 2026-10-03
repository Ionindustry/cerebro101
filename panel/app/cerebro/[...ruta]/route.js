// Pasarela del panel a la API del Cerebro.
// PENDIENTE (fase 1): sustituir las cabeceras de desarrollo por la sesión de Keycloak (OIDC).
const API = process.env.CEREBRO_API || "http://localhost:8000";

function cabeceras() {
  const h = { "Content-Type": "application/json" };
  if (process.env.PANEL_USUARIO_DESARROLLO) {
    h["X-Usuario"] = process.env.PANEL_USUARIO_DESARROLLO;
    h["X-Roles"] = process.env.PANEL_ROLES_DESARROLLO || "direccion,responsable";
    h["X-Departamentos"] = process.env.PANEL_DEPARTAMENTOS_DESARROLLO || "";
  }
  return h;
}

async function reenviar(req, { params }) {
  const { ruta } = await params;
  const url = `${API}/${ruta.join("/")}${new URL(req.url).search}`;
  const r = await fetch(url, {
    method: req.method,
    headers: cabeceras(),
    body: req.method === "GET" ? undefined : await req.text(),
  });
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}

export { reenviar as GET, reenviar as POST };
