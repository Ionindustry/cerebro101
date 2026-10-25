// Pasarela al servicio de voz (Whisper y Piper en el servidor).
import { cookies } from "next/headers";
import { COOKIE, modoDesarrollo, obtenerSesion } from "../../../lib/sesion";

const VOZ = process.env.VOZ_API || "http://localhost:8100";

export async function POST(req, { params }) {
  if (!modoDesarrollo() && !(await obtenerSesion((await cookies()).get(COOKIE)?.value))) {
    return Response.json({ error: "Sesión caducada" }, { status: 401 });
  }
  const { accion } = await params;
  if (!["transcribir", "hablar"].includes(accion)) return new Response("No encontrado", { status: 404 });
  const esHablar = accion === "hablar";
  const r = await fetch(`${VOZ}/${accion}`, {
    method: "POST",
    headers: esHablar ? { "Content-Type": "application/json" } : undefined,
    body: esHablar ? await req.text() : await req.formData(),
  });
  return new Response(r.body, { status: r.status, headers: { "Content-Type": r.headers.get("Content-Type") || "application/octet-stream" } });
}
