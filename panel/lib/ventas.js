// Ranking de ventas por tipo (GET ventas/ranking?dias=…&top=…). Puro: lo que se muestra sale de aquí para poder probarlo.
export const PERIODOS_VENTAS = [{ dias: 30, nombre: "30 días" }, { dias: 90, nombre: "3 meses" }, { dias: 180, nombre: "6 meses" }, { dias: 365, nombre: "12 meses" }, { dias: 730, nombre: "2 años" }];
export const TOPS = [5, 10, 15, 25];

/** Importe del ranking (texto con punto decimal) → «1.234,50 €»; «—» si no hay cifra. */
export function importeVentas(v) {
  const n = Number(v);
  return v === null || v === undefined || v === "" || Number.isNaN(n) ? "—" : `${n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

/** Cantidad sin decimales sobrantes: 12.00 → «12», 2.50 → «2,5». */
export function unidadesTexto(v) {
  const n = Number(v);
  return Number.isNaN(n) ? "—" : n.toLocaleString("es-ES", { maximumFractionDigits: 2 });
}

/** Línea de cabecera de un tipo: «Videovigilancia (CCTV) · 12.300,00 € · 41,2 % · 18 pedidos». */
export function resumenTipo(t) {
  if (!t) return "";
  return [t.nombre, importeVentas(t.importe), `${unidadesTexto(t.cuota_pct)} %`, `${t.pedidos} pedido${t.pedidos === 1 ? "" : "s"}`].join(" · ");
}

/** Texto para copiar o pegar en un correo: un bloque por tipo con sus artículos y fabricantes. */
export function rankingTexto(r) {
  if (!r?.tipos?.length) return "Sin ventas en el periodo.";
  const bloques = r.tipos.map((t) => {
    const art = t.articulos.map((a, i) => `  ${i + 1}. ${a.nombre} (${a.codigo})${a.marca ? ` · ${a.marca}` : ""} — ${importeVentas(a.importe)} · ${unidadesTexto(a.unidades)} uds`).join("\n");
    const fab = t.fabricantes.map((m, i) => `  ${i + 1}. ${m.nombre} — ${importeVentas(m.importe)}`).join("\n");
    return `${resumenTipo(t)}\n Artículos:\n${art}\n Fabricantes:\n${fab}`;
  });
  return `Ranking de ventas ${r.desde} a ${r.hasta} (excl.) · total ${importeVentas(r.total)}\n\n${bloques.join("\n\n")}`;
}
