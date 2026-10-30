"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { COLUMNAS_ORDENABLES, ESTADOS, MODOS, ORDENES, estadisticasQuery, estadoEtiqueta, fechaTexto, filtroDeAlerta, filtroDesdeDashboard, filtroTexto, filtrosAQuery, importeCorto, mensajeAlertas, mensajeDeError, queryAFiltros, rutaNoExiste, totalTexto } from "../../../lib/licitaciones";
import { Fallo, pedir, pedirCerebro } from "../cliente";
import Dashboard from "./Dashboard";

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
  const [stats, setStats] = useState({ datos: null, cargando: true, error: "" });
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(true);
  const ultimaStats = useRef(0);

  useEffect(() => {
    const n = ++ultima.current;
    setCargando(true); setError(null);
    pedir(`tenders?${filtrosAQuery(queryAFiltros(new URLSearchParams(clave)))}&limit=20`)
      .then((d) => { if (n === ultima.current) { setItems(d.items); setTotal(d.total); setCursor(d.siguiente_cursor); setAviso(d.aviso || ""); } })
      .catch((e) => { if (n === ultima.current) { setError(e); setItems([]); setTotal(null); setCursor(null); } })
      .finally(() => { if (n === ultima.current) setCargando(false); });
  }, [clave]);

  // El dashboard agrega sobre TODO lo que cumple los filtros (no solo la página): una petición aparte para no frenar la lista.
  useEffect(() => {
    const n = ++ultimaStats.current;
    setStats((x) => ({ ...x, cargando: true, error: "" }));
    pedir(`tenders/estadisticas?${estadisticasQuery(queryAFiltros(new URLSearchParams(clave)))}`)
      .then((d) => { if (n === ultimaStats.current) setStats({ datos: d, cargando: false, error: "" }); })
      .catch((e) => { if (n === ultimaStats.current) setStats({ datos: null, cargando: false, error: rutaNoExiste(e) ? "El resumen necesita actualizar el motor de licitaciones." : mensajeDeError(e?.status, e?.detalle) }); });
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

  const irA = (nuevo) => { const q = filtrosAQuery(nuevo).toString(); router.push(q ? `/licitaciones/buscar?${q}` : "/licitaciones/buscar"); };
  const desdeDashboard = (tipo, valor) => { const nuevo = filtroDesdeDashboard(queryAFiltros(new URLSearchParams(clave)), tipo, valor); setF(nuevo); irA(nuevo); };
  const ordenar = (columna) => { const nuevo = { ...queryAFiltros(new URLSearchParams(clave)), orden: COLUMNAS_ORDENABLES[columna] }; setF(nuevo); irA(nuevo); };
  const ordenActual = queryAFiltros(new URLSearchParams(clave)).orden;
  const porSignificado = !!queryAFiltros(new URLSearchParams(clave)).modo && queryAFiltros(new URLSearchParams(clave)).q.trim().length >= 2;
  const Cabecera = ({ columna, children }) => {
    const activa = !porSignificado && ordenActual === COLUMNAS_ORDENABLES[columna];
    return (
      <th aria-sort={activa ? (columna === "plazo" ? "ascending" : "descending") : "none"}>
        {porSignificado ? children : <button type="button" className="lic-th-orden" onClick={() => ordenar(columna)} title="Ordenar por esta columna">{children}{activa ? (columna === "plazo" ? " ↑" : " ↓") : ""}</button>}
      </th>
    );
  };

  return (
    <div className="lic lic-ancho">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <div className="lic-fila lic-titulo">
        <h1>Buscar licitaciones</h1>
        <button type="button" className="boton no" aria-expanded={filtrosAbiertos} aria-controls="lic-filtros" onClick={() => setFiltrosAbiertos((a) => !a)}>
          {filtrosAbiertos ? "Ocultar filtros" : "Mostrar filtros"}
        </button>
      </div>
      <div className={`lic-pantalla${filtrosAbiertos ? " con-filtros" : ""}`}>
        <aside id="lic-filtros" className="lic-lateral" hidden={!filtrosAbiertos} aria-label="Filtros">
      <form className="tarjeta lic-form lic-filtros" onSubmit={enviar} role="search">
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
        </aside>
        <div className="lic-principal">
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

          <Dashboard st={stats.datos} cargando={stats.cargando} error={stats.error} filtros={queryAFiltros(new URLSearchParams(clave))} alFiltrar={desdeDashboard} />
          {porSignificado && <p className="meta" role="note">Las cifras cuentan las licitaciones que contienen tus palabras; la lista de abajo se ordena por parecido de significado.</p>}

          <p className="meta" aria-live="polite">{cargando && items.length === 0 ? "Buscando…" : totalTexto(total)}</p>
          {aviso && <p className="meta" role="note">{aviso}</p>}
          {error && (error.status === 503 && f.modo ? <p role="alert" className="lic-error">La búsqueda por significado no está disponible ahora. Prueba «Por palabras».</p> : <Fallo e={error} />)}
          {!error && !cargando && items.length === 0 && <p className="meta">No hay licitaciones con esos filtros.</p>}
          {items.length > 0 && (
            <div className="tarjeta lic-tabla-caja">
              <table className="lic-tabla lic-tabla-resultados">
                <thead>
                  <tr>
                    <th>Estado</th><th>Licitación</th><th>Organismo</th>
                    <Cabecera columna="importe">Importe</Cabecera>
                    <Cabecera columna="plazo">Plazo</Cabecera>
                    <Cabecera columna="actualizada">Actualizada</Cabecera>
                  </tr>
                </thead>
                <tbody>{items.map((x) => <Fila key={x.id} x={x} />)}</tbody>
              </table>
            </div>
          )}
          {cursor && <div><button className="boton no" onClick={mas} disabled={cargando}>{cargando ? "Cargando…" : "Cargar más"}</button></div>}
        </div>
      </div>
    </div>
  );
}

/** Una licitación en la tabla: el título enlaza a su ficha. El plazo solo cuenta mientras la licitación sigue abierta. */
function Fila({ x }) {
  const conPlazo = x.plazo_presentacion && (x.estado === "abierta" || x.estado === "anuncio_previo");
  return (
    <tr>
      <td><span className={`lic-etiqueta ${x.estado}`}>{estadoEtiqueta(x.estado)}</span></td>
      <td><Link href={`/licitaciones/expedientes/${x.id}`} className="lic-titulo-fila">{x.titulo || "(sin título)"}</Link>{x.expediente ? <span className="meta lic-bloque">{x.expediente}</span> : null}</td>
      <td>{x.comprador?.nombre || "—"}</td>
      <td className="lic-num" title={x.importe ? "Valor estimado sin IVA" : undefined}>{x.importe ? importeCorto(x.importe.valor) : "—"}</td>
      <td className="lic-num">{conPlazo ? fechaTexto(x.plazo_presentacion) : "—"}</td>
      <td className="lic-num">{x.actualizada_en ? fechaTexto(x.actualizada_en, false) : "—"}</td>
    </tr>
  );
}

export default function Buscar() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Buscador /></Suspense>;
}
