"use client";
import { useCallback, useEffect, useState } from "react";
import { comprobacionTexto, cumpleEtiqueta, evidenciaTexto, fechaTexto } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

/** La comparativa de productos y ventaja competitiva: estrategia, productos por requisito, ventajas por criterio, riesgos y lo que falta. Cada afirmación enseña la evidencia en que se apoya, para que
 *  una persona la compruebe. Es un informe de ayuda: lo hace Claude o ChatGPT con las fichas de 101.cat y se repite con el botón de su paso. `version` cambia al avanzar la preparación y la recarga. */
export default function Comparativa({ id, version }) {
  const [d, setD] = useState(undefined);       // undefined = cargando; null = sin acceso
  const [abierto, setAbierto] = useState(false);
  const cargar = useCallback(async () => {
    try { setD((await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/comparativa`)).comparativa); }
    catch { setD((x) => (x === undefined ? null : x)); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar, version]);
  if (d === undefined || d === null) return null;
  const c = d.contenido, ev = d.evidencias;
  const Evid = ({ ids }) => (ids?.length > 0 ? <span className="meta"> Evidencia: {ids.map((i) => evidenciaTexto(i, ev)).join("; ")}</span> : null);
  return (
    <section className="tarjeta" aria-label="Comparativa de productos y ventaja competitiva">
      <header>
        <h3>Comparativa y ventaja competitiva</h3>
        <button className="boton no" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>{abierto ? "Ocultar" : "Ver"}</button>
      </header>
      <p className="meta">Hecha con {d.proveedor === "claude" ? "Claude" : "ChatGPT"}{d.modelo ? ` (${d.modelo})` : ""} el {fechaTexto(d.actualizado)}, con las fichas técnicas de 101.cat. {comprobacionTexto(c.comprobacion)}. Lo «sin datos» no está comprobado. Compara con lo que exige el pliego, no con otros licitadores.</p>
      {c.estrategia && <p><strong>Estrategia:</strong> {c.estrategia}</p>}
      {abierto && (
        <>
          <h4>Productos por requisito</h4>
          <ul className="lic-lista">
            {c.requisitos.map((r, i) => (
              <li key={i} className="tarjeta lic-item">
                <span className="titulo">{r.requisito}</span>
                {r.recomendado ? <span><strong>Recomendado:</strong> {r.recomendado}</span> : <span className="meta">Sin producto confirmado.</span>}
                {r.candidatos.map((k, j) => { const [txt, cl] = cumpleEtiqueta(k.cumple); return (
                  <span key={j} className="lic-fila"><span className={`lic-etiqueta ${cl}`}>{txt}</span><span>{k.producto}</span>{k.detalle && <span className="meta">{k.detalle}</span>}<Evid ids={k.evidencia} />{k.degradado && <span className="lic-etiqueta aviso">No citó evidencia válida</span>}</span>
                ); })}
                {r.brecha && <span className="meta">Falta: {r.brecha}</span>}
              </li>
            ))}
          </ul>
          {c.ventajas.length > 0 && (<><h4>Ventaja competitiva por criterio</h4>
            <ul className="lic-lista">{c.ventajas.map((v, i) => (
              <li key={i} className="tarjeta lic-item"><span className="lic-fila"><span className="titulo">{v.criterio}</span>{v.peso && <span className="lic-etiqueta">{v.peso}</span>}</span><span>{v.ventaja}</span>{v.como_destacarla && <span className="meta">Cómo destacarla: {v.como_destacarla}</span>}<Evid ids={v.evidencia} /></li>
            ))}</ul></>)}
          {c.riesgos.length > 0 && (<><h4>Riesgos</h4><ul>{c.riesgos.map((r, i) => <li key={i}>{r.riesgo}{r.mitigacion && <span className="meta"> — {r.mitigacion}</span>}</li>)}</ul></>)}
          {c.pendientes.length > 0 && (<><h4>Datos que faltan</h4><ul>{c.pendientes.map((p, i) => <li key={i}>{p}</li>)}</ul></>)}
        </>
      )}
    </section>
  );
}
