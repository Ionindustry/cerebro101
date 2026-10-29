"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ESTADOS, MODOS, ORDENES, filtroDeAlerta, filtroTexto, filtrosAQuery, mensajeAlertas, queryAFiltros, totalTexto } from "../../../lib/licitaciones";
import { Fallo, Item, pedir, pedirCerebro } from "../cliente";

function Buscador() {
  const router = useRouter();
  const sp = useSearchParams();
  const clave = sp.toString();                                   // la dirección de la página ES la búsqueda: se puede compartir
  const [f, setF] = useState(() => queryAFiltros(sp));
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(null);
  const [aviso, setAviso] = useState("");
  const [cursor, setCursor] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const ultima = useRef(0);

  useEffect(() => {
    const n = ++ultima.current;
    setCargando(true); setError(null);
    pedir(`tenders?${filtrosAQuery(queryAFiltros(new URLSearchParams(clave)))}&limit=20`)
      .then((d) => { if (n === ultima.current) { setItems(d.items); setTotal(d.total); setCursor(d.siguiente_cursor); setAviso(d.aviso || ""); } })
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
  const [alerta, setAlerta] = useState({ abierta: false, nombre: "", estado: "", error: null });
  const guardarAlerta = async (ev) => {
    ev.preventDefault();
    const filtro = filtroDeAlerta(queryAFiltros(new URLSearchParams(clave)));
    setAlerta((a) => ({ ...a, estado: "guardando", error: null }));
    try {
      await pedirCerebro("licitaciones/alertas", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nombre: alerta.nombre, ambito: "personal", filtro, eventos: ["licitacion.nueva"], canal: "panel" }) });
      setAlerta({ abierta: false, nombre: "", estado: "guardada", error: null });
    } catch (e) { setAlerta((a) => ({ ...a, estado: "", error: e })); }
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
          <label>Cómo buscar
            <select value={f.modo} onChange={poner("modo")}>
              {MODOS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
            <span className="ayuda">«Por significado» encuentra licitaciones de lo mismo aunque no usen tus palabras (p. ej. «cámaras de seguridad» → «videovigilancia»)</span>
          </label>
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

      {(() => {
        const filtro = filtroDeAlerta(queryAFiltros(new URLSearchParams(clave)));
        if (Object.keys(filtro).length === 0) return null;
        return (
          <div className="tarjeta lic-alerta-guardar">
            {alerta.estado === "guardada" ? <p role="status">Alerta guardada. <Link href="/licitaciones/alertas">Ver mis alertas</Link></p> : !alerta.abierta ? (
              <button className="boton no" onClick={() => setAlerta((a) => ({ ...a, abierta: true, estado: "" }))}>Guardar como alerta</button>
            ) : (
              <form className="lic-fila" onSubmit={guardarAlerta}>
                <input type="text" value={alerta.nombre} onChange={(e) => setAlerta((a) => ({ ...a, nombre: e.target.value }))} maxLength={120} required placeholder="Nombre de la alerta" aria-label="Nombre de la alerta" />
                <button className="boton si" type="submit" disabled={alerta.estado === "guardando"}>Guardar</button>
                <button className="boton no" type="button" onClick={() => setAlerta((a) => ({ ...a, abierta: false }))}>Cancelar</button>
                <span className="meta">Avisará de las nuevas que cumplan: {filtroTexto(filtro)}</span>
              </form>
            )}
            {alerta.error && <p role="alert" className="lic-error">{mensajeAlertas(alerta.error.status)}</p>}
          </div>
        );
      })()}

      <p className="meta" aria-live="polite">{cargando && items.length === 0 ? "Buscando…" : totalTexto(total)}</p>
      {aviso && <p className="meta" role="note">{aviso}</p>}
      {error && (error.status === 503 && f.modo ? <p role="alert" className="lic-error">La búsqueda por significado no está disponible ahora. Prueba «Por palabras».</p> : <Fallo e={error} />)}
      {!error && !cargando && items.length === 0 && <p className="meta">No hay licitaciones con esos filtros.</p>}
      <ul className="lic-lista">{items.map((x) => <Item key={x.id} x={x} />)}</ul>
      {cursor && <div><button className="boton no" onClick={mas} disabled={cargando}>{cargando ? "Cargando…" : "Cargar más"}</button></div>}
    </div>
  );
}

export default function Buscar() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Buscador /></Suspense>;
}
