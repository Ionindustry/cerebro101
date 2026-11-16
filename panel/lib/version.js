/** Versión del código que corre (los 7 primeros caracteres del commit). «desconocida» es una imagen construida a mano o antes de existir este indicador. */
export const versionCorta = (v) => {
  const t = String(v ?? "").trim().toLowerCase();
  return /^[0-9a-f]{7,40}$/.test(t) ? t.slice(0, 7) : "desconocida";
};

/** Qué enseñar al pie del menú: la versión del panel y, si la API lleva otra, un aviso (pasa a medias de una actualización: basta repetirla). Pura. */
export function textoVersion(panel, api) {
  const p = versionCorta(panel);
  const a = api == null ? null : versionCorta(api);
  if (a && p !== "desconocida" && a !== "desconocida" && p !== a) {
    return { texto: `Versión ${p} · la API lleva ${a}`, aviso: "El panel y la API están en versiones distintas: ejecuta otra vez ./scripts/actualizar.sh" };
  }
  return { texto: `Versión ${p}`, aviso: "" };
}
