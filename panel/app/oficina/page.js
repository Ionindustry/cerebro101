"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ESTADOS, estadoDemo } from "../../lib/oficina";

const REFRESCO = 4000;
const APROBACION = { libre: "Actúa solo", simple: "Pide una firma", doble: "Pide dos firmas" };

function hace(fecha) {
  if (!fecha) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(fecha).getTime()) / 1000));
  if (s < 10) return "ahora mismo";
  if (s < 60) return `hace ${s} s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}

export default function Oficina() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(false);
  const [sinWebgl, setSinWebgl] = useState(false);
  const [demo, setDemo] = useState(false);
  const [tick, setTick] = useState(0);
  const [sala, setSala] = useState(null);
  const [agenteId, setAgenteId] = useState(null);
  const [detalle, setDetalle] = useState(null);
  const [tip, setTip] = useState(null);
  const [lista, setLista] = useState(false);
  const caja = useRef(null);
  const ctl = useRef(null);

  const cargar = useCallback(() =>
    fetch("/cerebro/oficina")
      .then((r) => { if (r.status === 401) { window.location.href = "/auth/login"; return null; } if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => { if (d) { setDatos(d); setError(false); } })
      .catch(() => setError(true)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, REFRESCO); return () => clearInterval(t); }, [cargar]);
  useEffect(() => { if (!demo) return; const t = setInterval(() => setTick((n) => n + 1), 2600); return () => clearInterval(t); }, [demo]);

  const departamentos = datos?.departamentos || [];
  const simulado = useMemo(() => (demo ? estadoDemo(departamentos, tick) : null), [demo, tick, departamentos]);
  const agentes = useMemo(() => {
    const m = {};
    for (const d of departamentos) for (const a of d.agentes) {
      const sim = simulado?.[a.id];
      m[a.id] = { ...a, departamento: d.id, estado: sim ? sim.estado : a.estado, detalle: sim ? sim.detalle : a.detalle };
    }
    return m;
  }, [departamentos, simulado]);
  const cuenta = useMemo(() => {
    const c = { trabajando: 0, esperando: 0, reposo: 0 };
    Object.values(agentes).forEach((a) => { c[a.estado] += 1; });
    return c;
  }, [agentes]);

  // La escena 3D se construye una vez (y de nuevo solo si cambian los departamentos o sus agentes)
  const forma = departamentos.map((d) => d.id + ":" + d.agentes.map((a) => a.id).join(",")).join("|");
  useEffect(() => {
    if (!forma || !caja.current) return;
    let vivo = true, c = null;
    import("../../lib/escena3d").then(({ crearOficina }) => {
      if (!vivo) return;
      try {
        c = crearOficina({
          contenedor: caja.current,
          departamentos: departamentos.map((d) => ({ id: d.id, nombre: d.nombre, agentes: d.agentes.map((a) => ({ id: a.id, director: a.director })) })),
          alSeleccionarAgente: (id) => { setAgenteId(id); setSala(null); c.enfocarAgente(id); },
          alSeleccionarSala: (id) => { setSala(id); setAgenteId(null); c.enfocarSala(id); },
          alPasarPor: (id, x, y) => setTip(id ? { id, x, y } : null),
        });
        ctl.current = c;
        c.actualizar(agentes);
      } catch (e) { console.warn("Sin WebGL", e); setSinWebgl(true); }
    });
    return () => { vivo = false; ctl.current = null; c?.destruir(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forma]);
  useEffect(() => { ctl.current?.actualizar(agentes); }, [agentes]);

  const volver = useCallback(() => { setSala(null); setAgenteId(null); setDetalle(null); ctl.current?.vistaGeneral(); }, []);
  useEffect(() => { const f = (e) => { if (e.key === "Escape") volver(); }; window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f); }, [volver]);
  const elegirSala = (id) => { setSala(id); setAgenteId(null); ctl.current?.enfocarSala(id); };
  const elegirAgente = (id) => { setAgenteId(id); setSala(null); ctl.current?.enfocarAgente(id); };

  // Detalle del agente elegido: se refresca mientras está abierto
  useEffect(() => {
    if (!agenteId) { setDetalle(null); return; }
    let vivo = true;
    const leer = () => fetch(`/cerebro/oficina/agentes/${agenteId}`).then((r) => (r.ok ? r.json() : null)).then((d) => vivo && d && setDetalle(d)).catch(() => {});
    leer();
    const t = setInterval(leer, 2500);
    return () => { vivo = false; clearInterval(t); };
  }, [agenteId]);
  useEffect(() => { ctl.current?.nombreSeleccionado(agenteId ? agentes[agenteId]?.nombre : ""); }, [agenteId, agentes]);

  const salaActiva = departamentos.find((d) => d.id === sala);
  const a = agenteId ? agentes[agenteId] : null;
  const ordenEstado = ["trabajando", "esperando", "reposo"];
  const sim = demo && a ? { estado: a.estado, detalle: a.detalle } : null;
  const mostrar = a ? { ...(detalle || {}), ...(a ? { id: a.id, nombre: a.nombre, subarea: a.subarea, estado: sim ? sim.estado : (detalle?.estado || a.estado) } : {}) } : null;
  const vistaTip = tip ? agentes[tip.id] : null;

  return (
    <>
      <header className="of-cabecera">
        <div>
          <div className="of-etiqueta"><i /> JARVIS / OFICINA</div>
          <h1 className="of-titulo">Oficina<span>.</span></h1>
        </div>
        <div className="of-chips" aria-live="polite">
          <span className="of-chip trabajando"><b>{cuenta.trabajando}</b> trabajando</span>
          <span className="of-chip esperando"><b>{cuenta.esperando}</b> esperando aprobación</span>
          <span className="of-chip"><b>{cuenta.reposo}</b> en reposo</span>
          <button className="of-boton" onClick={() => { setDemo((d) => !d); setTick(0); }} aria-pressed={demo}>{demo ? "Salir de la demostración" : "Ver demostración"}</button>
          <button className="of-boton" onClick={() => setLista((v) => !v)} aria-pressed={lista || !!sala || !!agenteId}>Lista</button>
          {(sala || agenteId) && <button className="of-boton" onClick={volver}>← Toda la oficina</button>}
        </div>
      </header>
      {demo && <div className="of-demo" role="status">Demostración: los estados son de ejemplo, no actividad real.</div>}
      {error && <div className="of-demo of-error" role="status">No hay conexión con el Cerebro; se muestra la última información recibida.</div>}

      <div className="of-escena">
        <div className="of3" ref={caja} onMouseLeave={() => setTip(null)} />
        {!datos && !error && <p className="meta of-cargando">Cargando la oficina…</p>}
        {sinWebgl && <p className="meta of-cargando">Tu navegador no puede mostrar la vista 3D (WebGL). La lista de la derecha tiene la misma información.</p>}
        {!agenteId && !sala && <p className="of-ayuda" aria-hidden="true">Arrastra para mover · rueda para acercar · pulsa una sala o un agente</p>}
        {vistaTip && (
          <div className="of-tip" style={{ left: Math.min(tip.x + 16, (caja.current?.clientWidth || 600) - 250), top: Math.max(8, tip.y + 16) }} role="tooltip">
            <b>{vistaTip.nombre}</b>
            <span>{vistaTip.subarea}</span>
            <em style={{ color: ESTADOS[vistaTip.estado].color }}>{ESTADOS[vistaTip.estado].nombre}</em>
            {vistaTip.detalle && <span>{vistaTip.detalle}</span>}
          </div>
        )}

        <aside className={`of-lateral${lista || sala || agenteId ? "" : " solo-lectores"}`} aria-label="Estado de los agentes">
          {mostrar ? (
            <DetalleAgente d={mostrar} demo={demo} sim={sim} agentes={agentes} volver={() => { setAgenteId(null); ctl.current?.vistaGeneral(); }} />
          ) : salaActiva ? (
            <>
              <h2>{salaActiva.nombre}</h2>
              <p className="meta">{salaActiva.agentes.length} agentes{!salaActiva.detalle_visible ? " · el detalle de su trabajo solo lo ve su departamento" : ""}</p>
              <ul className="of-lista">
                {[...salaActiva.agentes].sort((x, y) => ordenEstado.indexOf(agentes[x.id].estado) - ordenEstado.indexOf(agentes[y.id].estado)).map((ag) => {
                  const v = agentes[ag.id]; return (
                    <li key={ag.id}><button className="of-dep" onClick={() => elegirAgente(ag.id)}>
                      <span className="of-estado" style={{ background: ESTADOS[v.estado].color }} aria-hidden="true" />
                      <span><b>{ag.nombre}</b>{ag.director ? <small> · dirige</small> : null}
                        <span className="meta" style={{ display: "block" }}>{ESTADOS[v.estado].nombre}{v.detalle ? ` · ${v.detalle}` : ""}</span></span>
                    </button></li>);
                })}
              </ul>
            </>
          ) : (
            <>
              <h2>Departamentos</h2>
              <ul className="of-lista">
                {departamentos.map((d) => {
                  const t = d.agentes.filter((x) => agentes[x.id]?.estado === "trabajando").length, e = d.agentes.filter((x) => agentes[x.id]?.estado === "esperando").length;
                  return (
                    <li key={d.id}><button className="of-dep" onClick={() => elegirSala(d.id)}>
                      <span className="of-estado" style={{ background: t ? "#f2584b" : e ? "#c98a0b" : "#c9c9ce" }} aria-hidden="true" />
                      <span><b>{d.nombre}</b><span className="meta"> · {d.agentes.length} agentes{t ? ` · ${t} trabajando` : ""}{e ? ` · ${e} esperando` : ""}</span></span>
                    </button></li>);
                })}
              </ul>
              {!demo && datos?.eventos?.length > 0 && (
                <>
                  <h2>Última actividad</h2>
                  <ul className="of-lista">
                    {datos.eventos.map((e, i) => (
                      <li key={i}><span className="of-estado" style={{ background: e.ok ? "#2e7d4f" : "#b3261e" }} aria-hidden="true" />
                        <div><b>{e.agente}</b><div className="meta">{e.texto} · {hace(e.cuando)}{e.ok ? "" : " · con error"}</div></div></li>))}
                  </ul>
                </>
              )}
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function DetalleAgente({ d, demo, sim, volver }) {
  const est = ESTADOS[d.estado] || ESTADOS.reposo;
  return (
    <div className="of-detalle">
      <button className="of-atras" onClick={volver}>← Volver</button>
      <h2>{d.nombre}</h2>
      <p className="meta">{d.subarea}{d.director ? " · dirige el departamento" : ""}</p>
      <div className="of-estadogrande" style={{ borderColor: est.color }}>
        <span className="of-estado" style={{ background: est.color }} aria-hidden="true" />
        <div>
          <b>{est.nombre}</b>
          {sim?.detalle || d.ahora ? <div>{sim?.detalle || d.ahora}</div> : d.estado === "reposo" && d.ultima ? <div className="meta">Última tarea: {d.ultima}{d.desde ? ` · ${hace(d.desde)}` : ""}</div> : null}
          {!demo && d.estado === "trabajando" && d.desde && <div className="meta">{hace(d.desde)}</div>}
        </div>
      </div>

      {d.tareas && <><h3>Qué hace</h3><p>{d.tareas}</p></>}
      {d.herramientas && (
        <>
          <h3>Herramientas</h3>
          <div className="of-tags">{d.herramientas.map((h) => <span key={h}>{h}</span>)}</div>
          <p className="meta">{APROBACION[d.aprobacion]}{d.programado ? " · trabaja también de forma programada" : ""} · datos de sensibilidad {d.sensibilidad}</p>
        </>
      )}

      {d.detalle_visible === false && (
        <p className="of-aviso">El detalle de lo que hace este agente solo lo ven las personas de su departamento y la dirección.</p>
      )}
      {d.detalle_visible && (
        <>
          {d.pendientes?.length > 0 && (
            <>
              <h3>Espera tu aprobación</h3>
              {d.pendientes.map((p) => (
                <div key={p.id} className="of-pend">
                  <b>{p.resumen || p.accion}</b>
                  {p.vista?.campos?.slice(0, 4).map(([k, v]) => <div key={k} className="meta"><b>{k}:</b> {String(v).slice(0, 140)}</div>)}
                  <Link href="/aprobaciones">Ir a Aprobaciones →</Link>
                </div>
              ))}
            </>
          )}
          <h3>Pasos recientes</h3>
          {d.pasos?.length ? (
            <ol className="of-pasos">{d.pasos.map((p, i) => <li key={i}><span>{p.texto}</span><time>{hace(p.cuando)}</time></li>)}</ol>
          ) : <p className="meta">Todavía no ha hecho nada desde que arrancó el sistema.</p>}
          {d.acciones?.length > 0 && (
            <>
              <h3>Acciones registradas</h3>
              <ol className="of-pasos">{d.acciones.map((x, i) => <li key={i}><span>{x.texto}{x.ok ? "" : " · con error"}</span><time>{hace(x.cuando)}</time></li>)}</ol>
            </>
          )}
        </>
      )}
    </div>
  );
}
