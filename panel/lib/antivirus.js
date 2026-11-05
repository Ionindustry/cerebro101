// El texto de la tarjeta «Antivirus» a partir de GET /salud/antivirus (puro, para poder probarlo).
const fechaTexto = (iso) => { try { return new Date(iso).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }); } catch { return iso || ""; } };

/** {nivel: bien|aviso|mal, titulo, lineas[], ayuda?} */
export function antivirusResumen(e) {
  if (!e) return { nivel: "aviso", titulo: "sin datos", lineas: [], ayuda: null };
  if (e.estado === "no_responde") return { nivel: "mal", titulo: "no responde", lineas: [e.motivo], ayuda: "docker compose logs --tail 30 clamav  ·  docker compose restart clamav" };
  const lineas = [e.fecha_firmas ? `Firmas del ${fechaTexto(e.fecha_firmas)} (hace ${Math.round(e.edad_horas)} h)` : "No se puede leer la fecha de las firmas", `Versión: ${e.version || "?"}`];
  if (e.estado === "ok") return { nivel: "bien", titulo: `firmas al día (hace ${Math.round(e.edad_horas)} h)`, lineas, ayuda: null };
  const rechaza = e.edad_horas != null && e.edad_horas > e.limite_horas;
  return {
    nivel: rechaza || e.edad_horas == null ? "mal" : "aviso",
    titulo: rechaza ? "firmas viejas: se rechazan los documentos" : "firmas viejas",
    lineas: [...lineas, e.motivo].filter(Boolean),
    ayuda: "docker compose exec clamav freshclam --log=/tmp/freshclam.log  ·  docker compose restart clamav",
  };
}
