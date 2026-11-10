// Descarga del fichero original de un documento de pliego, solo para personas de Licitaciones y Dirección (la API lo comprueba otra vez con la sesión).
// Es una ruta aparte de la pasarela /cerebro porque esa lleva solo texto: aquí el contenido va tal cual (binario) y con cabeceras que impiden que el navegador lo «interprete».
import { cookies } from "next/headers";
import { COOKIE, obtenerSesion } from "../../../../../lib/sesion";
import { rutaFicheroPliego } from "../../../../../lib/licitaciones";

const API = process.env.CEREBRO_API || "http://localhost:8000";
const PLAZO_MS = 60000;

async function cabeceras() {
  if (process.env.PANEL_USUARIO_DESARROLLO) {
    return {
      "X-Usuario": process.env.PANEL_USUARIO_DESARROLLO,
      "X-Roles": process.env.PANEL_ROLES_DESARROLLO || "direccion,responsable",
      "X-Departamentos": process.env.PANEL_DEPARTAMENTOS_DESARROLLO || "",
    };
  }
  const s = await obtenerSesion((await cookies()).get(COOKIE)?.value);
  return s ? { Authorization: `Bearer ${s.acceso}` } : null;
}

const error = (status, detalle) => new Response(JSON.stringify({ detail: detalle }), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });

export async function GET(_req, { params }) {
  const { motor, n } = await params;
  const ruta = rutaFicheroPliego(motor, n);
  if (!ruta) return error(400, "Documento no válido");
  const h = await cabeceras();
  if (!h) return error(401, "Sesión caducada");
  let r;
  try {
    r = await fetch(`${API}/${ruta}`, { headers: h, signal: AbortSignal.timeout(PLAZO_MS), cache: "no-store" });
  } catch {
    return error(503, "No se puede conectar con la API");
  }
  if (!r.ok) {
    let detalle = "No se ha podido descargar el documento";
    try { detalle = (await r.json()).detail || detalle; } catch {}
    return error(r.status, typeof detalle === "string" ? detalle : "No se ha podido descargar el documento");
  }
  const salida = {
    "Content-Type": r.headers.get("content-type") || "application/octet-stream",
    "Content-Disposition": r.headers.get("content-disposition") || "attachment",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; sandbox",
  };
  return new Response(await r.arrayBuffer(), { status: 200, headers: salida });
}
