"use client";
import { useCallback, useEffect, useState } from "react";
import { barrasPorDia, contarPorDepartamento, esperaTexto, filtrarPorDepartamento, nombreDepartamento, repartoPorDepartamento } from "../../lib/aprobaciones";
import { etiquetaDia } from "../../lib/kpi";

// Todo lo que requiere aprobación lo firma Dirección, una sola persona
const NIVELES = { simple: "Requiere tu firma", doble: "Requiere tu firma" };
const DECISIONES = { aprobada: "Aprobada", rechazada: "Rechazada" };

const fecha = (f) => (f ? new Date(f).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" }) : "");
const etiqueta = (k) => { const t = k.replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
const texto = (v) => (v === null || v === undefined ? "—" : typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v, null, 2) : String(v));

// Todo lo que hay que revisar antes de decidir: la vista preparada por el sistema (p. ej. un correo completo) o, si no la hay, los datos de la acción
function camposDe(s) {
  const d = s.datos || {};
  if (d.vista?.campos?.length) return d.vista.campos;
  const args = d.argumentos || {};
  return Object.keys(args).length ? Object.entries(args).map(([k, v]) => [etiqueta(k), texto(v)]) : [];
}

function Detalle({ s }) {
  const campos = camposDe(s);
  return (
    <div className="ap-detalle">
      <dl className="ap-ficha">
        <div><dt>Lo propone</dt><dd>{s.agente} · departamento {s.departamento}</dd></div>
        <div><dt>Acción</dt><dd>{s.accion}</dd></div>
        <div><dt>Fecha</dt><dd>{fecha(s.creado)}</dd></div>
      </dl>
      {s.datos?.vista?.titulo && <h3>{s.datos.vista.titulo}</h3>}
      {campos.length > 0 ? (
        <dl className="ap-campos">
          {campos.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{texto(v)}</dd></div>
          ))}
        </dl>
      ) : <p className="meta">Esta solicitud no trae más datos que el resumen.</p>}
    </div>
  );
}

function Tarjeta({ s, abierta, alternar, hijos, cabecera }) {
  return (
    <article className={`tarjeta ap-tarjeta${abierta ? " abierta" : ""}`}>
      <button className="ap-cabecera" aria-expanded={abierta} onClick={alternar}>
        <span className="ap-titulo">{s.datos?.resumen || s.accion}</span>
        {cabecera}
        <span className="ap-flecha" aria-hidden="true">{abierta ? "−" : "+"}</span>
        <span className="meta ap-sub">{s.agente} · {s.departamento} · {fecha(s.estado === "pendiente" ? s.creado : s.actualizado)}</span>
      </button>
      {abierta && <div className="ap-cuerpo"><Detalle s={s} />{hijos}</div>}
    </article>
  );
}

function FiltroDepartamentos({ conteos, dep, setDep, deps, total, etiquetaTodos = "Todos" }) {
  if (conteos.length === 0 && !dep) return null;
  return (
    <div className="ap-filtros ap-deps" role="group" aria-label="Filtrar por departamento">
      <button aria-pressed={!dep} onClick={() => setDep("")}>{etiquetaTodos}{total !== undefined ? <span className="ap-n">{total}</span> : null}</button>
      {conteos.map(({ id, n }) => (
        <button key={id} aria-pressed={dep === id} onClick={() => setDep(dep === id ? "" : id)}>
          {nombreDepartamento(deps, id)}{n !== undefined ? <span className="ap-n">{n}</span> : null}
        </button>
      ))}
    </div>
  );
}

function Dashboard({ resumen, deps, dias, setDias, irA }) {
  if (!resumen) return <p className="meta">Cargando el resumen…</p>;
  const { pendientes: p, resueltas: r } = resumen;
  const { filas, max } = repartoPorDepartamento(resumen, deps);
  const serie = barrasPorDia(resumen.por_dia, 90);
  const w = 100 / serie.length;
  const marcas = serie.length > 31 ? 15 : serie.length > 14 ? 5 : 1;
  const tiles = [
    ["Pendientes de tu firma", p.total, p.total ? "esperan decisión" : "nada pendiente"],
    ["Lleva más tiempo esperando", esperaTexto(p.espera_max_horas), p.total ? "la más antigua" : ""],
    [`Aprobadas (${dias} d)`, r.aprobadas, ""],
    [`Rechazadas (${dias} d)`, r.rechazadas, ""],
    ["Tasa de aprobación", r.tasa_aprobacion === null ? "—" : `${r.tasa_aprobacion} %`, `${r.total} decididas`],
    ["Tiempo medio de decisión", esperaTexto(r.tiempo_medio_horas), "desde que se pide hasta que firmas"],
  ];
  return (
    <div className="ap-dash">
      <div className="ap-filtros" role="group" aria-label="Periodo">
        {[7, 30, 90].map((d) => <button key={d} aria-pressed={dias === d} onClick={() => setDias(d)}>Últimos {d} días</button>)}
      </div>
      <div className="ap-tiles">
        {tiles.map(([nombre, valor, ayuda]) => (
          <article key={nombre} className="kp-tarjeta"><div className="kp-nombre">{nombre}</div><div className="kp-valor">{valor}</div>{ayuda && <div className="kp-ayuda">{ayuda}</div>}</article>
        ))}
      </div>

      <section className="kp-seccion">
        <h2>Por departamento</h2>
        {filas.length === 0 ? <p className="meta">Todavía no hay aprobaciones en este periodo.</p> : (
          <ul className="ap-reparto">
            {filas.map((f) => (
              <li key={f.id}>
                <button className="ap-dep-nombre" onClick={() => irA(f.id)} title="Ver sus aprobaciones pendientes">{f.nombre}</button>
                <span className="kp-barra" aria-hidden="true">
                  <i style={{ width: `${(f.pendientes / max) * 100}%`, background: "#c98a0b" }} />
                  <i style={{ width: `${(f.aprobadas / max) * 100}%`, background: "#2e7d4f" }} />
                  <i style={{ width: `${(f.rechazadas / max) * 100}%`, background: "#8a8a84" }} />
                </span>
                <span className="ap-reparto-n"><b>{f.pendientes}</b> pendientes · {f.aprobadas} aprobadas · {f.rechazadas} rechazadas</span>
              </li>
            ))}
          </ul>
        )}
        <div className="kp-leyenda"><span><i style={{ background: "#c98a0b" }} />Pendientes</span><span><i style={{ background: "#2e7d4f" }} />Aprobadas</span><span><i style={{ background: "#8a8a84" }} />Rechazadas</span></div>
      </section>

      <section className="kp-seccion">
        <h2>Por día</h2>
        <svg viewBox="0 0 100 110" preserveAspectRatio="none" role="img" aria-label="Solicitudes creadas, aprobadas y rechazadas por día" className="kp-grafico">
          {[0, 45, 90].map((y) => <line key={y} x1="0" x2="100" y1={100 - y} y2={100 - y} stroke="#e4e4e0" strokeWidth=".3" vectorEffect="non-scaling-stroke" />)}
          {serie.map((b, i) => <rect key={"c" + i} x={i * w + w * 0.1} width={w * 0.8} y={100 - b.hCreadas} height={b.hCreadas} fill="#d4d4d8"><title>{`${etiquetaDia(b.dia)}: ${b.creadas} solicitadas`}</title></rect>)}
          {serie.map((b, i) => <rect key={"a" + i} x={i * w + w * 0.25} width={w * 0.24} y={100 - b.hAprobadas} height={b.hAprobadas} fill="#2e7d4f"><title>{`${etiquetaDia(b.dia)}: ${b.aprobadas} aprobadas`}</title></rect>)}
          {serie.map((b, i) => <rect key={"r" + i} x={i * w + w * 0.51} width={w * 0.24} y={100 - b.hRechazadas} height={b.hRechazadas} fill="#8a8a84"><title>{`${etiquetaDia(b.dia)}: ${b.rechazadas} rechazadas`}</title></rect>)}
        </svg>
        <div className="kp-eje">{serie.map((d, i) => <span key={d.dia} style={{ visibility: i % marcas === 0 || i === serie.length - 1 ? "visible" : "hidden" }}>{etiquetaDia(d.dia)}</span>)}</div>
        <div className="kp-leyenda"><span><i style={{ background: "#d4d4d8" }} />Solicitadas</span><span><i style={{ background: "#2e7d4f" }} />Aprobadas</span><span><i style={{ background: "#8a8a84" }} />Rechazadas</span></div>
      </section>

      <div className="ap-dos">
        {[["Agentes que más piden", resumen.por_agente, "agente"], ["Acciones más frecuentes", resumen.por_accion, "accion"]].map(([titulo, lista, campo]) => (
          <section key={titulo} className="kp-seccion">
            <h2>{titulo}</h2>
            {lista.length === 0 ? <p className="meta">Sin datos en este periodo.</p> : (
              <ul className="kp-herr">{lista.map((x) => <li key={x[campo]}><span className="kp-herr-n">{x[campo]}</span><span className="kp-herr-v">{x.total}</span></li>)}</ul>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

export default function Aprobaciones() {
  const [pestana, setPestana] = useState("pendientes");
  const [deps, setDeps] = useState({});
  const [dep, setDep] = useState("");              // departamento elegido (clasifica pendientes e historial)
  const [resumen, setResumen] = useState(null);
  const [dias, setDias] = useState(30);
  const [lista, setLista] = useState(null);
  const [hist, setHist] = useState({ items: [], total: 0 });
  const [pagina, setPagina] = useState(0);
  const [filtro, setFiltro] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [abierta, setAbierta] = useState(null);
  const [comentario, setComentario] = useState({});
  const [avisos, setAvisos] = useState({});
  const [ocupada, setOcupada] = useState(null);

  const cargar = useCallback(() => fetch("/cerebro/aprobaciones").then((r) => r.json()).then(setLista).catch(() => setLista([])), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 15000); return () => clearInterval(t); }, [cargar]);

  useEffect(() => { fetch("/cerebro/departamentos").then((r) => r.json()).then(setDeps).catch(() => {}); }, []);
  const cargarResumen = useCallback(() => fetch(`/cerebro/aprobaciones/resumen?dias=${dias}`).then((r) => (r.ok ? r.json() : null)).then((d) => d && setResumen(d)).catch(() => {}), [dias]);
  useEffect(() => { cargarResumen(); }, [cargarResumen, lista]);

  const cargarHistorial = useCallback((p = 0, reemplazar = true) => {
    const q = new URLSearchParams({ pagina: String(p) });
    if (dep) q.set("departamento", dep);
    if (filtro) q.set("decision", filtro);
    if (busqueda.trim()) q.set("q", busqueda.trim());
    return fetch(`/cerebro/aprobaciones/historial?${q}`).then((r) => r.json())
      .then((d) => setHist((h) => ({ ...d, items: reemplazar ? d.items : [...h.items, ...d.items] })))
      .catch(() => {});
  }, [filtro, busqueda, dep]);
  useEffect(() => { if (pestana === "historial") { setPagina(0); cargarHistorial(0, true); } }, [pestana, cargarHistorial]);

  async function decidir(s, aprobado) {
    setOcupada(s.id);
    try {
      const r = await fetch(`/cerebro/aprobaciones/${s.id}`, { method: "POST", body: JSON.stringify({ aprobado, canal: "panel", comentario: comentario[s.id] || "" }) });
      const d = await r.json();
      if (!r.ok) return setAvisos((a) => ({ ...a, [s.id]: d.detail || "No se ha podido guardar la decisión" }));
      setAbierta(null);
      setAvisos((a) => ({ ...a, _ultimo: `${aprobado ? "Aprobada" : "Rechazada"}: ${s.datos?.resumen || s.accion}. Queda guardada en el historial.` }));
      await cargar();
    } finally { setOcupada(null); }
  }

  const pendientes = lista?.length ?? 0;
  const visibles = filtrarPorDepartamento(lista || [], dep);
  const irA = (id) => { setDep(id); setPestana("pendientes"); };
  const conteosHistorial = Object.entries(resumen?.resueltas.por_departamento || {}).map(([id, v]) => ({ id, n: v.aprobadas + v.rechazadas })).sort((a, b) => b.n - a.n);
  return (
    <>
      <h1>Aprobaciones</h1>
      <div className="ap-pestanas" role="tablist">
        <button role="tab" aria-selected={pestana === "resumen"} onClick={() => setPestana("resumen")}>Resumen</button>
        <button role="tab" aria-selected={pestana === "pendientes"} onClick={() => setPestana("pendientes")}>Pendientes{pendientes ? <span className="contador">{pendientes}</span> : null}</button>
        <button role="tab" aria-selected={pestana === "historial"} onClick={() => setPestana("historial")}>Historial</button>
      </div>
      {avisos._ultimo && pestana === "pendientes" && <div className="ap-hecho" role="status">{avisos._ultimo}</div>}

      {pestana === "resumen" && <Dashboard resumen={resumen} deps={deps} dias={dias} setDias={setDias} irA={irA} />}

      {pestana === "pendientes" && (
        <>
          <FiltroDepartamentos conteos={contarPorDepartamento(lista || [])} dep={dep} setDep={setDep} deps={deps} total={pendientes} />
          {lista === null && <p className="meta">Cargando…</p>}
          {lista?.length === 0 && <p className="meta">No hay nada esperando tu decisión. Lo que apruebes o rechaces queda guardado en el Historial.</p>}
          {lista?.length > 0 && visibles.length === 0 && <p className="meta">No hay nada pendiente de {nombreDepartamento(deps, dep)}.</p>}
          <div className="lista">
            {visibles.map((s) => (
              <Tarjeta key={s.id} s={s} abierta={abierta === s.id} alternar={() => setAbierta(abierta === s.id ? null : s.id)}
                cabecera={<span className="nivel">{NIVELES[s.nivel] || "Requiere tu firma"}</span>}
                hijos={
                  <div className="ap-decidir">
                    <label>Comentario (opcional)
                      <textarea rows={2} value={comentario[s.id] || ""} onChange={(e) => setComentario((c) => ({ ...c, [s.id]: e.target.value }))} placeholder="Motivo de tu decisión" />
                    </label>
                    <div className="botones">
                      <button className="boton si" disabled={ocupada === s.id} onClick={() => decidir(s, true)}>Aprobar</button>
                      <button className="boton no" disabled={ocupada === s.id} onClick={() => decidir(s, false)}>Rechazar</button>
                    </div>
                    {avisos[s.id] && <div className="aviso" role="alert">{avisos[s.id]}</div>}
                  </div>
                } />
            ))}
          </div>
        </>
      )}

      {pestana === "historial" && (
        <>
          <FiltroDepartamentos conteos={conteosHistorial} dep={dep} setDep={setDep} deps={deps} etiquetaTodos="Todos los departamentos" />
          <div className="ap-filtros">
            {[["", "Todas"], ["aprobada", "Aprobadas"], ["rechazada", "Rechazadas"]].map(([v, n]) => (
              <button key={v} aria-pressed={filtro === v} onClick={() => setFiltro(v)}>{n}</button>
            ))}
            <input type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} placeholder="Buscar por resumen, acción o agente" aria-label="Buscar en el historial" />
          </div>
          <p className="meta">{hist.total} {hist.total === 1 ? "decisión guardada" : "decisiones guardadas"}</p>
          <div className="lista">
            {hist.items.map((s) => {
              const dec = (s.decisiones || [])[0] || (s.decisiones || []).slice(-1)[0];
              return (
                <Tarjeta key={s.id} s={s} abierta={abierta === s.id} alternar={() => setAbierta(abierta === s.id ? null : s.id)}
                  cabecera={<span className={`ap-estado ${s.estado}`}>{DECISIONES[s.estado]}</span>}
                  hijos={
                    <div className="ap-resolucion">
                      <h3>Decisión</h3>
                      {(s.decisiones || []).map((d, i) => (
                        <p key={i}><b>{DECISIONES[d.aprobado ? "aprobada" : "rechazada"]}</b> por {d.usuario}{d.fecha ? ` · ${fecha(d.fecha)}` : ""}{d.canal === "voz" ? " · por voz" : ""}
                          {d.comentario ? <span className="meta"> — «{d.comentario}»</span> : null}</p>
                      ))}
                      {s.estado === "aprobada" && (
                        <>
                          <h3>Lo que se ejecutó</h3>
                          <pre className="ap-resultado">{s.resultado ? s.resultado.slice(0, 1500) : "No consta resultado de la ejecución."}</pre>
                        </>
                      )}
                    </div>
                  } />
              );
            })}
          </div>
          {hist.items.length < hist.total && (
            <button className="boton no ap-mas" onClick={() => { const p = pagina + 1; setPagina(p); cargarHistorial(p, false); }}>Ver más</button>
          )}
          {hist.total === 0 && <p className="meta">Todavía no hay decisiones guardadas.</p>}
        </>
      )}
    </>
  );
}
