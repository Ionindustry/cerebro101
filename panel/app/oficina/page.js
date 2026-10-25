"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { COLOR, ESTADOS, crearEscena, estadoDemo } from "../../lib/oficina";

const REFRESCO = 4000;

function hace(fecha) {
  if (!fecha) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(fecha).getTime()) / 1000));
  if (s < 60) return "hace unos segundos";
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}

export default function Oficina() {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(false);
  const [demo, setDemo] = useState(false);
  const [tick, setTick] = useState(0);
  const [sala, setSala] = useState(null);
  const [resalto, setResalto] = useState(null);
  const [tip, setTip] = useState(null);
  const [lista, setLista] = useState(false);
  const caja = useRef(null);

  const cargar = useCallback(() =>
    fetch("/cerebro/oficina")
      .then((r) => { if (r.status === 401) { window.location.href = "/auth/login"; return null; } if (!r.ok) throw new Error(); return r.json(); })
      .then((d) => { if (d) { setDatos(d); setError(false); } })
      .catch(() => setError(true)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, REFRESCO); return () => clearInterval(t); }, [cargar]);
  useEffect(() => { if (!demo) return; const t = setInterval(() => setTick((n) => n + 1), 2600); return () => clearInterval(t); }, [demo]);

  const departamentos = datos?.departamentos || [];
  const escena = useMemo(() => crearEscena(departamentos.map((d) => ({ id: d.id, nombre: d.nombre, agentes: d.agentes.map((a) => ({ id: a.id, director: a.director })) }))),
    // la forma de la oficina solo cambia si cambian los departamentos o sus agentes, no con el estado
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [departamentos.map((d) => d.id + ":" + d.agentes.map((a) => a.id).join(",")).join("|")]);

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

  // Zoom a la sala elegida (la vista se anima; con «reducir movimiento» salta directamente)
  const completo = escena.viewBox;
  const objetivo = useMemo(() => {
    const s = escena.salas.find((x) => x.id === sala);
    if (!s) return completo;
    const [x, y, w, h] = s.caja, [, , W, H] = completo, razon = W / H;
    let ancho = Math.max(w + 90, (h + 90) * razon), alto = ancho / razon;
    return [x + w / 2 - ancho / 2, y + h / 2 - alto / 2 - 4, ancho, alto];
  }, [sala, escena, completo]);
  const [vista, setVista] = useState(completo);
  const actual = useRef(completo);
  useEffect(() => {
    const reducir = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const desde = actual.current, t0 = performance.now();
    let id;
    const paso = (t) => {
      const k = reducir ? 1 : Math.min(1, (t - t0) / 520), e = 1 - Math.pow(1 - k, 3);
      actual.current = desde.map((v, i) => v + (objetivo[i] - v) * e);
      setVista(actual.current);
      if (k < 1) id = requestAnimationFrame(paso);
    };
    id = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(id);
  }, [objetivo]);

  const mover = (e, a) => {
    const r = caja.current.getBoundingClientRect();
    setTip({ a, x: e.clientX - r.left, y: e.clientY - r.top });
  };
  const color = (id) => ESTADOS[agentes[id]?.estado || "reposo"].color;
  const salaActiva = departamentos.find((d) => d.id === sala);

  return (
    <>
      <header className="of-cabecera">
        <div className="of-etiqueta"><i /> JARVIS / OFICINA</div>
        <h1 className="of-titulo">Oficina<span>.</span></h1>
        <p className="of-sub">Cada departamento con sus agentes. Quien trabaja se marca en coral; quien espera una firma, en ámbar. Pulsa una sala para acercarte.</p>
        <div className="of-chips" aria-live="polite">
          <span className="of-chip trabajando"><b>{cuenta.trabajando}</b> trabajando</span>
          <span className="of-chip esperando"><b>{cuenta.esperando}</b> esperando aprobación</span>
          <span className="of-chip"><b>{cuenta.reposo}</b> en reposo</span>
          <button className="of-boton" onClick={() => { setDemo((d) => !d); setTick(0); }} aria-pressed={demo}>{demo ? "Salir de la demostración" : "Ver demostración"}</button>
          <button className="of-boton" onClick={() => setLista((v) => !v)} aria-pressed={lista || !!sala}>Lista</button>
          {sala && <button className="of-boton" onClick={() => setSala(null)}>← Toda la oficina</button>}
        </div>
        {demo && <div className="of-demo" role="status">Demostración: los estados son de ejemplo, no actividad real.</div>}
        {error && <div className="of-demo of-error" role="status">No hay conexión con el Cerebro; se muestra la última información recibida.</div>}
      </header>

      <div className="of-cuerpo">
        <div className="of-escena" ref={caja} onMouseLeave={() => setTip(null)}>
          {!datos && !error && <p className="meta">Cargando la oficina…</p>}
          {datos && (
            <svg viewBox={vista.map((n) => n.toFixed(1)).join(" ")} role="img" aria-label={`Oficina con ${departamentos.length} departamentos y ${cuenta.trabajando + cuenta.esperando + cuenta.reposo} agentes. La lista de la derecha tiene la misma información en texto.`}>
              <defs>
                <radialGradient id="of-hoja" cx="35%" cy="30%" r="75%"><stop offset="0%" stopColor={COLOR.arbolClaro} /><stop offset="100%" stopColor={COLOR.arbol} /></radialGradient>
                <linearGradient id="of-capsula" x1="0" x2="1"><stop offset="0%" stopColor="#2b2b2f" /><stop offset="45%" stopColor="#0d0d0f" /><stop offset="100%" stopColor="#000" /></linearGradient>
              </defs>
              {escena.suelos.map((o, i) => (
                <polygon key={i} points={o.puntos} fill={o.relleno} stroke={o.linea ? (o.sala === sala ? COLOR.senal : o.linea) : "none"} strokeWidth={o.sala === sala ? 2.2 : 0.9}
                  className={o.sala ? "of-sala" : undefined} onClick={o.sala ? () => setSala(o.sala === sala ? null : o.sala) : undefined} />
              ))}
              {escena.objetos.map((o, i) => {
                if (o.tipo === "poli") return <polygon key={i} points={o.puntos} fill={o.relleno} stroke="#c2c2c8" strokeWidth="0.5" strokeLinejoin="round" />;
                if (o.tipo === "arbol") return (
                  <g key={i}><ellipse cx={o.cx} cy={o.cy + 1} rx={o.r * 0.95} ry={o.r * 0.42} fill="#000" opacity=".08" />
                    <circle cx={o.cx} cy={o.cy - o.r * 0.9} r={o.r} fill="url(#of-hoja)" stroke="#c4c4ca" strokeWidth=".6" /></g>);
                if (o.tipo === "pantalla") {
                  const est = agentes[o.agente]?.estado;
                  return <rect key={i} x={o.cx - 5} y={o.cy - 7} width="10" height="7" rx="1" fill={est === "trabajando" ? COLOR.senal : est === "esperando" ? "#c98a0b" : COLOR.pantalla} opacity={est === "reposo" ? 0.9 : 1} />;
                }
                if (o.tipo === "agente") {
                  const a = agentes[o.id];
                  if (!a) return null;
                  const alto = o.director ? 25 : 21, ancho = 9;
                  return (
                    <g key={o.id} className={`of-agente ${a.estado}${resalto === o.id ? " resaltado" : ""}`} transform={`translate(${o.cx} ${o.cy})`}
                      tabIndex={0} role="button" aria-label={`${a.nombre}: ${ESTADOS[a.estado].nombre}${a.detalle ? ". " + a.detalle : ""}`}
                      onMouseMove={(e) => mover(e, a)} onMouseLeave={() => setTip(null)} onFocus={() => setResalto(o.id)} onBlur={() => setResalto(null)}
                      onClick={() => setSala(o.departamento)}>
                      <ellipse cx="0" cy="1" rx="8" ry="3.4" fill="#000" opacity=".16" />
                      {a.estado === "esperando" && <ellipse className="of-anillo" cx="0" cy="1" rx="10.5" ry="4.6" fill="none" stroke="#c98a0b" strokeWidth="1.6" />}
                      <g className="of-cuerpo">
                        <rect x={-ancho / 2} y={-alto} width={ancho} height={alto} rx={ancho / 2} fill="url(#of-capsula)" />
                        {o.director && <rect x={-ancho / 2} y={-alto * 0.55} width={ancho} height="2" fill="#fff" opacity=".85" />}
                        {a.estado !== "reposo" && <circle className="of-punto" cx="0" cy={-alto - 5} r="2.8" fill={color(o.id)} />}
                      </g>
                    </g>);
                }
                return null;
              })}
              {escena.salas.map((s) => {
                const d = departamentos.find((x) => x.id === s.id);
                const n = d ? d.agentes.filter((a) => agentes[a.id]?.estado === "trabajando").length : 0;
                const w = Math.max(70, s.nombre.length * 6.4 + 34);
                return (
                  <g key={s.id} className="of-etiq" transform={`translate(${s.etiqueta.x} ${s.etiqueta.y})`} onClick={() => setSala(s.id === sala ? null : s.id)}>
                    <rect x={-w / 2} y="-9" width={w} height="18" rx="9" fill="#fff" stroke="#e1e1e5" />
                    <circle cx={-w / 2 + 10} cy="0" r="3" fill={n ? COLOR.senal : "#bdbdc4"} />
                    <text x={-w / 2 + 19} y="3.4" fontSize="9.5" letterSpacing=".6" fill="#1c1c1c" style={{ textTransform: "uppercase", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>{s.nombre}</text>
                  </g>);
              })}
            </svg>
          )}
          {tip && (
            <div className="of-tip" style={{ left: Math.min(tip.x + 14, (caja.current?.clientWidth || 600) - 250), top: tip.y + 14 }} role="tooltip">
              <b>{tip.a.nombre}</b>
              <span>{tip.a.subarea}</span>
              <em style={{ color: ESTADOS[tip.a.estado].color }}>{ESTADOS[tip.a.estado].nombre}</em>
              {tip.a.detalle && <span>{tip.a.detalle}</span>}
            </div>
          )}
        <aside className={`of-lateral${lista || sala ? "" : " solo-lectores"}`} aria-label="Estado de los agentes">
          {salaActiva ? (
            <>
              <h2>{salaActiva.nombre}</h2>
              <p className="meta">{salaActiva.agentes.length} agentes{!salaActiva.detalle_visible ? " · el detalle de su trabajo solo lo ve su departamento" : ""}</p>
              <ul className="of-lista">
                {[...salaActiva.agentes].sort((a, b) => ["trabajando", "esperando", "reposo"].indexOf(agentes[a.id].estado) - ["trabajando", "esperando", "reposo"].indexOf(agentes[b.id].estado))
                  .map((a) => { const v = agentes[a.id]; return (
                    <li key={a.id} onMouseEnter={() => setResalto(a.id)} onMouseLeave={() => setResalto(null)}>
                      <span className="of-estado" style={{ background: ESTADOS[v.estado].color }} aria-hidden="true" />
                      <div><b>{a.nombre}</b>{a.director ? <small> · dirige</small> : null}
                        <div className="meta">{ESTADOS[v.estado].nombre}{v.detalle ? ` · ${v.detalle}` : ""}</div></div>
                    </li>); })}
              </ul>
            </>
          ) : (
            <>
              <h2>Departamentos</h2>
              <ul className="of-lista">
                {departamentos.map((d) => {
                  const t = d.agentes.filter((a) => agentes[a.id]?.estado === "trabajando").length, e = d.agentes.filter((a) => agentes[a.id]?.estado === "esperando").length;
                  return (
                    <li key={d.id}><button className="of-dep" onClick={() => setSala(d.id)}>
                      <span className="of-estado" style={{ background: t ? COLOR.senal : e ? "#c98a0b" : "#c9c9ce" }} aria-hidden="true" />
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
      </div>
    </>
  );
}
