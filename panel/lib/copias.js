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

// ---- Ajustes de las copias (GET/POST salud/copias/ajustes; solo Dirección) ----
export const CAMPOS_COPIAS = ["conservar", "extra", "conservar_extra", "dias_aviso"];

/** Los ajustes del servidor → el texto de cada casilla del formulario. */
export function ajustesAFormulario(a) {
  const v = a?.valores || {};
  return { conservar: String(v.conservar ?? 7), extra: v.extra || "", conservar_extra: String(v.conservar_extra ?? 0), dias_aviso: String(v.dias_aviso ?? 3) };
}

const RE_EXTRA = /^\/(?:mnt\/[a-z]|media\/[A-Za-z0-9._-]+|srv|home\/[A-Za-z0-9._-]+)\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/;

function entero(texto, nombre, min, max) {
  const t = String(texto ?? "").trim();
  if (!/^\d{1,4}$/.test(t)) return { error: `«${nombre}» tiene que ser un número entero.` };
  const n = Number(t);
  return n < min || n > max ? { error: `«${nombre}» tiene que estar entre ${min} y ${max}.` } : { n };
}

/** El formulario → el cuerpo que se envía; o un mensaje claro. El servidor vuelve a comprobarlo todo. Pura. */
export function ajustesAEnvio(f) {
  const c = entero(f.conservar, "Copias que se conservan", 1, 60);
  if (c.error) return { error: c.error };
  const ce = entero(f.conservar_extra, "Copias que se conservan en la segunda ubicación", 0, 365);
  if (ce.error) return { error: ce.error };
  const d = entero(f.dias_aviso, "Días sin copia para avisar", 1, 14);
  if (d.error) return { error: d.error };
  const bruta = String(f.extra ?? "").trim();
  const extra = bruta.replace(/\/+$/, "");
  if (bruta && (!extra || !RE_EXTRA.test(extra) || extra.split("/").some((p) => p === "." || p === ".."))) {
    return { error: "La segunda ubicación tiene que ser una carpeta del servidor, por ejemplo /mnt/d/Copias101 (sin espacios ni símbolos raros, y dentro de una carpeta, no la raíz de la unidad)." };
  }
  return { cuerpo: { conservar: c.n, extra, conservar_extra: ce.n, dias_aviso: d.n } };
}

/** La frase que explica lo que hace cada ajuste a partir de lo elegido. */
export function resumenAjustesCopias(f) {
  const e = String(f.extra || "").trim();
  const n = Number(f.conservar_extra);
  return `Se guardan las últimas ${f.conservar} copias en el servidor` + (e ? `, y una segunda copia en ${e}${n > 0 ? ` (allí, las últimas ${n})` : " (allí no se borra nada)"}` : " (sin segunda copia)") + `. Se avisa a soporte@ si pasan ${f.dias_aviso} días sin una correcta.`;
}
