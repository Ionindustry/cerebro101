"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
  COMPETENCIA_VACIA, MERCADOS_EJEMPLO, ORDENES_COMPETENCIA, adjudicacionesDeCompetidor, bajaTexto, competenciaAQuery, competenciaAcotada, cuotaTexto,
  fechaCivilTexto, fichaOrgHref, importeTexto, mercadoTexto, vencenDeMercado, muestraPoca, muestraTexto, queryACompetencia, tendenciaEtiqueta, totalTexto,
} from "../../../lib/licitaciones";
import { Fallo, pedir } from "../cliente";

// Últimas adjudicaciones de una empresa en este mercado: se piden al abrir la fila, no antes.
function UltimasAdjudicaciones({ filtros, organizacionId }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    pedir(`awards?${adjudicacionesDeCompetidor(filtros, organizacionId)}`).then(setD).catch(setError);
  }, [filtros, organizacionId]);
  if (error) return <Fallo e={error} />;
  if (!d) return <p className="meta" aria-busy="true">Cargando…</p>;
  if (d.items.length === 0) return <p className="meta">No hay adjudicaciones de esta empresa con estos filtros.</p>;
  return (
    <table className="lic-tabla">
      <thead><tr><th>Fecha</th><th>Licitación</th><th>Comprador</th><th>Adjudicado</th><th>Baja</th><th>Ofertas</th></tr></thead>
      <tbody>
        {d.items.map((a) => (
          <tr key={a.id}>
            <td>{fechaCivilTexto(a.fecha_adjudicacion)}</td>
            <td><Link href={`/licitaciones/expedientes/${a.licitacion_id}`}>{a.titulo || a.expediente || "(sin título)"}</Link>{a.lote && a.lote !== "1" ? ` · lote ${a.lote}` : ""}</td>
            <td>{fichaOrgHref(a.comprador?.id) ? <Link href={fichaOrgHref(a.comprador.id)}>{a.comprador.nombre || "—"}</Link> : (a.comprador?.nombre || "—")}</td>
            <td>{importeTexto((a.importes || []).find((i) => i.significado === "adjudicado" && i.impuestos === "sin_iva"))}</td>
            <td>{bajaTexto(a.baja)}</td>
            <td>{a.ofertas_recibidas ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Competidor({ x, filtros, puesto }) {
  const t = tendenciaEtiqueta(x.tendencia);
  const [abierta, setAbierta] = useState(false);
  const o = x.organizacion || {};
  return (
    <li className="tarjeta lic-comp">
      <header className="lic-fila">
        <span className="lic-puesto" aria-label={`Puesto ${puesto}`}>{puesto}</span>
        <h3>{fichaOrgHref(o.id) ? <Link href={fichaOrgHref(o.id)}>{o.nombre || "(sin nombre)"}</Link> : (o.nombre || "(sin nombre)")}</h3>
        {o.nif && <span className="meta">{o.nif}</span>}
        <span className={`lic-etiqueta ${t.clase}`} title={t.ayuda}>{t.texto}</span>
      </header>
      <div className="lic-cuota" role="img" aria-label={`Cuota de mercado ${cuotaTexto(x.cuota)}`}><span style={{ width: `${Math.max(1, Math.min(100, (x.cuota || 0) * 100))}%` }} /></div>
      <dl className="lic-ficha">
        <div><dt>Cuota del mercado</dt><dd>{cuotaTexto(x.cuota)}</dd></div>
        <div><dt>Contratos ganados</dt><dd>{x.contratos_ganados}</dd></div>
        <div><dt>Importe adjudicado</dt><dd>{importeTexto(x.importe_adjudicado)}</dd></div>
        <div><dt>Baja media / mediana</dt><dd>{bajaTexto(x.baja_media)} / {bajaTexto(x.baja_p50)}</dd></div>
        <div><dt>Última adjudicación</dt><dd>{x.ultima_adjudicacion ? fechaCivilTexto(x.ultima_adjudicacion) : "—"}</dd></div>
      </dl>
      <details onToggle={(e) => setAbierta(e.currentTarget.open)}>
        <summary>Sus últimas adjudicaciones en este mercado</summary>
        {abierta && <UltimasAdjudicaciones filtros={filtros} organizacionId={o.id} />}
      </details>
    </li>
  );
}

function Competencia() {
  const router = useRouter();
  const sp = useSearchParams();
  const clave = sp.toString();                                   // la dirección de la página ES la consulta: se puede compartir
  const [f, setF] = useState(() => queryACompetencia(sp));
  const filtros = queryACompetencia(new URLSearchParams(clave));
  const acotada = competenciaAcotada(filtros);
  const [d, setD] = useState(null);
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState(null);
  const ultima = useRef(0);

  useEffect(() => {
    const n = ++ultima.current;
    const fl = queryACompetencia(new URLSearchParams(clave));
    if (!competenciaAcotada(fl)) { setD(null); setItems([]); setCursor(null); setError(null); setCargando(false); return; }
    setCargando(true); setError(null);
    pedir(`competitors?${competenciaAQuery(fl)}&limit=20`)
      .then((r) => { if (n === ultima.current) { setD(r); setItems(r.items); setCursor(r.siguiente_cursor); } })
      .catch((e) => { if (n === ultima.current) { setError(e); setD(null); setItems([]); setCursor(null); } })
      .finally(() => { if (n === ultima.current) setCargando(false); });
  }, [clave]);

  const mas = async () => {
    setCargando(true);
    try {
      const r = await pedir(`competitors?${competenciaAQuery(filtros)}&limit=20&cursor=${encodeURIComponent(cursor)}`);
      setItems((a) => [...a, ...r.items]); setCursor(r.siguiente_cursor);
    } catch (e) { setError(e); } finally { setCargando(false); }
  };
  const enviar = (ev) => { ev.preventDefault(); const q = competenciaAQuery(f).toString(); router.push(q ? `/licitaciones/competencia?${q}` : "/licitaciones/competencia"); };
  const poner = (k) => (ev) => setF((x) => ({ ...x, [k]: ev.target.value }));

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <h1>Competencia</h1>
      <p className="meta">Quién gana los contratos de un mercado, cuánto se lleva y con qué baja. Elige el mercado con un CPV, una zona o un comprador.</p>
      <form className="tarjeta lic-form" onSubmit={enviar} role="search">
        <div className="lic-campos">
          <label>CPV<input type="text" value={f.cpv} onChange={poner("cpv")} placeholder="72 35125300" /><span className="ayuda">Códigos o prefijos de 2 a 8 cifras</span></label>
          <label>Zona (NUTS)<input type="text" value={f.nuts} onChange={poner("nuts")} placeholder="ES512" /><span className="ayuda">ES51 = Cataluña, ES512 = Girona</span></label>
          <label>Comprador (NIF)<input type="text" value={f.comprador} onChange={poner("comprador")} placeholder="P1708500E" /><span className="ayuda">NIF del organismo</span></label>
          <label>Adjudicado desde<input type="date" value={f.desde} onChange={poner("desde")} /></label>
          <label>Adjudicado hasta<input type="date" value={f.hasta} onChange={poner("hasta")} /></label>
          <label>Orden
            <select value={f.orden} onChange={poner("orden")}>
              <option value="">Mayor importe adjudicado</option>
              {ORDENES_COMPETENCIA.slice(1).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </label>
        </div>
        <div className="lic-fila">
          <button className="boton si" type="submit">Ver competidores</button>
          <button className="boton no" type="button" onClick={() => { setF(COMPETENCIA_VACIA); router.push("/licitaciones/competencia"); }}>Limpiar</button>
        </div>
      </form>

      {!acotada && (
        <section className="tarjeta" aria-labelledby="lic-comp-ej">
          <h2 id="lic-comp-ej">Para empezar</h2>
          <p className="meta">Sin un mercado no hay nada que comparar. Prueba con uno de estos:</p>
          <ul className="lic-fila">{MERCADOS_EJEMPLO.map(([t, c]) => <li key={c}><Link className="lic-etiqueta" href={`/licitaciones/competencia?cpv=${c}`}>{t} · CPV {c}</Link></li>)}</ul>
        </section>
      )}

      {acotada && (
        <>
          <div className="lic-fila"><h2>{mercadoTexto(filtros)}</h2><Link href={vencenDeMercado(filtros)} className="lic-vuelve">Ver los contratos que vencen en este mercado</Link></div>
          {error && <Fallo e={error} />}
          {d && (
            <>
              <p className="meta" aria-live="polite">{muestraTexto(d.muestra)} · {totalTexto(d.total).replace("resultados", "empresas").replace("resultado", "empresa")}</p>
              {muestraPoca(d.muestra) && <p role="status" className="lic-aviso">Hay pocas adjudicaciones detrás de estas cifras: tómalas como orientación, no como una cuota fiable.</p>}
              <p className="meta">La cuota es sobre el importe adjudicado (sin IVA) en este mercado. La baja solo se muestra cuando el presupuesto del lote es fiable.</p>
            </>
          )}
          {cargando && items.length === 0 && <p className="meta" aria-busy="true">Calculando…</p>}
          {!error && !cargando && d && items.length === 0 && <p className="meta">No hay adjudicaciones en este mercado y periodo. Prueba con un CPV más amplio (menos cifras) o un periodo más largo.</p>}
          <ol className="lic-lista">{items.map((x, i) => <Competidor key={x.organizacion?.id || i} x={x} filtros={filtros} puesto={i + 1} />)}</ol>
          {cursor && <div><button className="boton no" onClick={mas} disabled={cargando}>{cargando ? "Cargando…" : "Cargar más"}</button></div>}
        </>
      )}
    </div>
  );
}

export default function PaginaCompetencia() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Competencia /></Suspense>;
}
