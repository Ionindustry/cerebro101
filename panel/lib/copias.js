// El texto de la tarjeta «Copias de seguridad» a partir de GET /salud/copias (puro, para poder probarlo).
const bytesTexto = (n) => (n == null ? "" : n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const fechaTexto = (iso) => { try { return new Date(iso).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }); } catch { return iso || ""; } };

/** {nivel: bien|aviso|mal, titulo, lineas[], ayuda?} */
export function copiasResumen(e) {
  if (!e) return { nivel: "aviso", titulo: "sin datos", lineas: [], ayuda: null };
  const buena = e.ultima_correcta, ultima = e.ultima, rest = e.restauracion;
  const lineas = [];
  if (buena) lineas.push(`Última copia correcta: ${fechaTexto(buena.fecha)}${buena.bytes != null ? ` · ${bytesTexto(buena.bytes)}` : ""}`);
  else lineas.push("Todavía no consta ninguna copia correcta.");
  if (ultima && !ultima.ok) lineas.push(`La última copia FALLÓ (${fechaTexto(ultima.fecha)}): ${ultima.mensaje}`);
  if (rest) lineas.push(`Restauración probada: ${fechaTexto(rest.fecha)} · ${rest.ok ? "se puede restaurar" : `FALLÓ: ${rest.mensaje}`}`);
  else lineas.push("La restauración aún no se ha probado: ./scripts/probar_restauracion.sh");
  if (e.alerta) return { nivel: "mal", titulo: `llevas ${Math.floor(e.dias_sin_copia)} días sin una correcta`, lineas, ayuda: "Enciende el servidor y lanza ./scripts/copia_automatica.sh, o instala la tarea de Windows (autoarranque.ps1 -Instalar)." };
  if (ultima && !ultima.ok) return { nivel: "aviso", titulo: "la última copia falló", lineas, ayuda: "Mira el correo de soporte@ o lanza ./scripts/copia_automatica.sh a mano." };
  if (rest && !rest.ok) return { nivel: "mal", titulo: "la copia no se puede restaurar", lineas, ayuda: "Haz una copia nueva (./scripts/copia_automatica.sh) y vuelve a probarla." };
  if (!buena) return { nivel: "aviso", titulo: "sin copias todavía", lineas, ayuda: "Lanza ./scripts/copia_automatica.sh o instala la tarea de Windows." };
  return { nivel: rest ? "bien" : "aviso", titulo: rest ? "al día" : "al día (restauración sin probar)", lineas, ayuda: null };
}
