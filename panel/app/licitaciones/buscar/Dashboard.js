"use client";
import { useMemo } from "react";
import { calendarioPlazos, divisionEtiqueta, estadoEtiqueta, hoyMadrid, importeCorto, repartoBarras, tramoEtiqueta, zonaEtiqueta } from "../../../lib/licitaciones";

const DIAS = ["D", "L", "M", "X", "J", "V", "S"];
const n = (v) => new Intl.NumberFormat("es-ES").format(v ?? 0);

function Cifra({ titulo, valor, nota }) {
  return (
    <div className="tarjeta lic-cifra">
      <span className="lic-cifra-titulo">{titulo}</span>
      <span className="lic-cifra-valor">{valor}</span>
      {nota && <span className="meta">{nota}</span>}
    </div>
  );
}

/** Barras horizontales: si `alElegir` existe, cada fila es un botón que filtra la búsqueda por ese valor. */
function Barras({ titulo, grupos, etiqueta, alElegir, activo, vacio = "Sin datos", mostrarImporte = false }) {
  const filas = repartoBarras(grupos, etiqueta);
  return (
    <section className="tarjeta lic-grafico" aria-label={titulo}>
      <h3>{titulo}</h3>
      {filas.length === 0 ? <p className="meta">{vacio}</p> : (
        <ul className="dash-barras">
          {filas.map((g) => {
            const contenido = (
              <>
                <span className="dash-etiqueta">{g.etiqueta}</span>
                <span className="dash-pista" aria-hidden="true"><span className={`dash-relleno ${g.valor}`} style={{ width: `${g.pct}%` }} /></span>
                <span className="dash-cuenta">{n(g.cuenta)}{mostrarImporte && g.importe ? <span className="meta"> · {importeCorto(g.importe)}</span> : null}</span>
              </>
            );
            const elegible = alElegir && g.valor !== "" && g.valor !== "sin_importe" && g.valor !== "(sin nombre)";
            return (
              <li key={`${g.valor}|${g.nif || ""}`}>
                {elegible
                  ? <button type="button" className="dash-fila" aria-pressed={activo ? activo(g.valor) : undefined} onClick={() => alElegir(g.valor)} title="Filtrar por esto">{contenido}</button>
                  : <div className="dash-fila">{contenido}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Calendario({ plazos }) {
  const dias = useMemo(() => calendarioPlazos(plazos, hoyMadrid(), 60), [plazos]);
  const total = dias.reduce((a, d) => a + d.cuenta, 0);
  return (
    <section className="tarjeta lic-grafico lic-calendario" aria-label="Calendario de plazos">
      <h3>Plazos de los próximos 60 días <span className="meta">· {n(total)} {total === 1 ? "licitación vence" : "licitaciones vencen"}</span></h3>
      <div className="lic-cal-columnas" role="img" aria-label={`Licitaciones que vencen cada día durante los próximos 60 días: ${n(total)} en total`}>
        {dias.map((d) => (
          <span key={d.fecha} className={`lic-cal-dia${d.esHoy ? " hoy" : ""}${d.diaSemana === 0 || d.diaSemana === 6 ? " finde" : ""}`} title={`${d.fecha}: ${d.cuenta}`}>
            <span className="lic-cal-barra" style={{ height: `${d.cuenta > 0 ? Math.max(d.pct, 8) : 0}%` }} />
          </span>
        ))}
      </div>
      <div className="lic-cal-ejes" aria-hidden="true">
        {dias.map((d, i) => <span key={d.fecha}>{i === 0 || d.dia === 1 ? `${d.dia}/${d.fecha.slice(5, 7)}` : d.diaSemana === 1 ? DIAS[d.diaSemana] : ""}</span>)}
      </div>
    </section>
  );
}

/** El dashboard: cifras, estados, repartos, plazos y compradores de TODO lo que cumple los filtros. Pulsar un estado, una zona o un CPV filtra la búsqueda. */
export default function Dashboard({ st, cargando, error, filtros, alFiltrar }) {
  if (error) return <p className="meta" role="note">{error}</p>;
  if (!st) return <p className="meta" aria-live="polite">{cargando ? "Calculando el resumen…" : ""}</p>;
  if (st.total === 0) return null;
  const sel = (tipo) => (v) => alFiltrar(tipo, v);
  return (
    <div className="lic-dashboard" aria-busy={cargando}>
      <div className="lic-cifras">
        <Cifra titulo="Resultados" valor={n(st.total)} />
        <Cifra titulo="Importe total" valor={importeCorto(st.importe?.total)} nota={`${n(st.importe?.con_importe)} con importe · valor estimado sin IVA`} />
        <Cifra titulo="Importe medio" valor={importeCorto(st.importe?.medio)} />
        <Cifra titulo="Abiertas" valor={n(st.abiertas)} />
        <Cifra titulo="Vencen en 7 días" valor={n(st.vencen_7_dias)} />
      </div>
      <div className="lic-graficos">
        <Barras titulo="Por estado" grupos={st.estados} etiqueta={estadoEtiqueta} alElegir={sel("estado")} activo={(v) => filtros.estados.includes(v)} />
        <Barras titulo="Por importe" grupos={st.importes} etiqueta={tramoEtiqueta} />
        <Barras titulo="Por zona" grupos={st.zonas} etiqueta={zonaEtiqueta} alElegir={sel("zona")} activo={(v) => filtros.nuts.trim() === v} />
        <Barras titulo="Por sector (CPV)" grupos={st.cpv} etiqueta={divisionEtiqueta} alElegir={sel("cpv")} activo={(v) => filtros.cpv.trim() === v} />
      </div>
      <Calendario plazos={st.plazos} />
      <Barras titulo="Principales organismos" grupos={st.compradores} mostrarImporte vacio="Sin organismos" />
    </div>
  );
}

