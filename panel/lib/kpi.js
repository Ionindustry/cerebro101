// Formato de los KPI del panel de cada agente (sin React: se prueba con node --test).

const num = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });
const eur = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

export function formatearValor(valor, unidad = "") {
  if (valor === null || valor === undefined) return "—";
  if (unidad === "€") return eur.format(valor);
  if (unidad === "%") return `${num.format(valor)} %`;
  if (unidad === "min") return valor >= 120 ? `${num.format(valor / 60)} h` : `${num.format(valor)} min`;
  return num.format(valor);
}

export function unidadVisible(unidad = "") {
  return ["€", "%", "min", ""].includes(unidad) ? "" : unidad;
}

export function formatearDelta(delta) {
  if (delta === null || delta === undefined) return null;
  if (delta === 0) return { texto: "= igual que antes", signo: 0 };
  return { texto: `${delta > 0 ? "▲ +" : "▼ "}${delta} %`, signo: delta > 0 ? 1 : -1 };
}

// Barras de un gráfico: alturas relativas al máximo (con un mínimo para que un valor pequeño se vea)
export function barras(serie, clave, alto = 100) {
  const max = Math.max(1, ...serie.map((s) => s[clave] || 0));
  return serie.map((s) => ({ ...s, altura: s[clave] ? Math.max(3, Math.round((s[clave] / max) * alto)) : 0 }));
}

export function etiquetaDia(iso) {
  const [, m, d] = iso.split("-");
  return `${Number(d)}/${Number(m)}`;
}

export function segmentos(valores) {
  const total = valores.reduce((a, v) => a + v.n, 0);
  return total ? valores.map((v) => ({ ...v, ancho: (v.n / total) * 100 })) : [];
}
