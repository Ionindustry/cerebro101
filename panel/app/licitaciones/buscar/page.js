"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ESTADOS, ORDENES, filtrosAQuery, queryAFiltros, totalTexto } from "../../../lib/licitaciones";
import { Fallo, Item, pedir } from "../cliente";

function Buscador() {
  const router = useRouter();
  const sp = useSearchParams();
  const clave = sp.toString();                                   // la dirección de la página ES la búsqueda: se puede compartir
  const [f, setF] = useState(() => queryAFiltros(sp));
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(null);
  const [cursor, setCursor] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const ultima = useRef(0);

  useEffect(() => {
    const n = ++ultima.current;
    setCargando(true); setError(null);
    pedir(`tenders?${filtrosAQuery(queryAFiltros(new URLSearchParams(clave)))}&limit=20`)
      .then((d) => { if (n === ultima.current) { setItems(d.items); setTotal(d.total); setCursor(d.siguiente_cursor); } })
      .catch((e) => { if (n === ultima.current) { setError(e); setItems([]); setTotal(null); setCursor(null); } })
      .finally(() => { if (n === ultima.current) setCargando(false); });
  }, [clave]);

  const mas = async () => {
    setCargando(true);
    try {
      const d = await pedir(`tenders?${filtrosAQuery(queryAFiltros(new URLSearchParams(clave)))}&limit=20&cursor=${encodeURIComponent(cursor)}`);
      setItems((a) => [...a, ...d.items]); setCursor(d.siguiente_cursor);
    } catch (e) { setError(e); } finally { setCargando(false); }
  };
  const enviar = (ev) => { ev.preventDefault(); const q = filtrosAQuery(f).toString(); router.push(q ? `/licitaciones/buscar?${q}` : "/licitaciones/buscar"); };
  const poner = (k) => (ev) => setF((x) => ({ ...x, [k]: ev.target.value }));
  const alternar = (e) => setF((x) => ({ ...x, estados: x.estados.includes(e) ? x.estados.filter((y) => y !== e) : [...x.estados, e] }));

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <h1>Buscar licitaciones</h1>
      <form className="tarjeta lic-form" onSubmit={enviar} role="search">
        <div className="lic-campos">
          <label>Texto<input type="text" value={f.q} onChange={poner("q")} maxLength={200} placeholder="castellano o catalán" /></label>
          <label>CPV<input type="text" value={f.cpv} onChange={poner("cpv")} placeholder="72 35125300" /><span className="ayuda">Códigos o prefijos de 2 a 8 cifras</span></label>
          <label>Zona (NUTS)<input type="text" value={f.nuts} onChange={poner("nuts")} placeholder="ES512" /><span className="ayuda">ES51 = Cataluña, ES512 = Girona</span></label>
          <label>Importe mínimo (€, sin IVA)<input type="text" inputMode="decimal" value={f.importeMin} onChange={poner("importeMin")} /></label>
          <label>Importe máximo (€, sin IVA)<input type="text" inputMode="decimal" value={f.importeMax} onChange={poner("importeMax")} /></label>
          <label>Plazo de presentación hasta<input type="date" value={f.plazoHasta} onChange={poner("plazoHasta")} /></label>
          <label>Orden
            <select value={f.orden} onChange={poner("orden")}>
              <option value="">Automático</option>
              {ORDENES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="lic-estados">
          <legend>Estado</legend>
          {ESTADOS.map(([k, t]) => <label key={k}><input type="checkbox" checked={f.estados.includes(k)} onChange={() => alternar(k)} />{t}</label>)}
        </fieldset>
        <div className="lic-fila">
          <button className="boton si" type="submit">Buscar</button>
          <button className="boton no" type="button" onClick={() => { setF(queryAFiltros(new URLSearchParams())); router.push("/licitaciones/buscar"); }}>Limpiar</button>
        </div>
      </form>

      <p className="meta" aria-live="polite">{cargando && items.length === 0 ? "Buscando…" : totalTexto(total)}</p>
      {error && <Fallo e={error} />}
      {!error && !cargando && items.length === 0 && <p className="meta">No hay licitaciones con esos filtros.</p>}
      <ul className="lic-lista">{items.map((x) => <Item key={x.id} x={x} />)}</ul>
      {cursor && <div><button className="boton no" onClick={mas} disabled={cargando}>{cargando ? "Cargando…" : "Cargar más"}</button></div>}
    </div>
  );
}

export default function Buscar() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Buscador /></Suspense>;
}
