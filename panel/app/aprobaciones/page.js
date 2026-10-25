"use client";
import { useCallback, useEffect, useState } from "react";

const NIVELES = { simple: "Requiere tu firma", doble: "Requiere tu firma · solo en el panel" };
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
      {s.datos?.objetivo && <p><strong>Objetivo:</strong> {s.datos.objetivo}</p>}
      {Array.isArray(s.datos?.acciones) && (
        <div className="ap-lote">
          <p className="meta">Firmas una vez y se ejecutan estas {s.datos.acciones.length} acciones:</p>
          <ol>
            {s.datos.acciones.map((a, i) => (
              <li key={i}>
                <strong>{a.resumen}</strong>
                {a.vista?.campos?.length > 0 && (
                  <dl className="ap-campos">
                    {a.vista.campos.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{texto(v)}</dd></div>)}
                  </dl>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
      {s.datos?.vista?.titulo && <h3>{s.datos.vista.titulo}</h3>}
      {campos.length > 0 ? (
        <dl className="ap-campos">
          {campos.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{texto(v)}</dd></div>
          ))}
        </dl>
      ) : !s.datos?.acciones && <p className="meta">Esta solicitud no trae más datos que el resumen.</p>}
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

export default function Aprobaciones() {
  const [pestana, setPestana] = useState("pendientes");
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

  const cargarHistorial = useCallback((p = 0, reemplazar = true) => {
    const q = new URLSearchParams({ pagina: String(p) });
    if (filtro) q.set("decision", filtro);
    if (busqueda.trim()) q.set("q", busqueda.trim());
    return fetch(`/cerebro/aprobaciones/historial?${q}`).then((r) => r.json())
      .then((d) => setHist((h) => ({ ...d, items: reemplazar ? d.items : [...h.items, ...d.items] })))
      .catch(() => {});
  }, [filtro, busqueda]);
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
  return (
    <>
      <h1>Aprobaciones</h1>
      <div className="ap-pestanas" role="tablist">
        <button role="tab" aria-selected={pestana === "pendientes"} onClick={() => setPestana("pendientes")}>Pendientes{pendientes ? <span className="contador">{pendientes}</span> : null}</button>
        <button role="tab" aria-selected={pestana === "historial"} onClick={() => setPestana("historial")}>Historial</button>
      </div>
      {avisos._ultimo && pestana === "pendientes" && <div className="ap-hecho" role="status">{avisos._ultimo}</div>}

      {pestana === "pendientes" && (
        <>
          {lista === null && <p className="meta">Cargando…</p>}
          {lista?.length === 0 && <p className="meta">No hay nada esperando tu decisión. Lo que apruebes o rechaces queda guardado en el Historial.</p>}
          <div className="lista">
            {lista?.map((s) => (
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
