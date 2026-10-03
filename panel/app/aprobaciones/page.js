"use client";
import { useEffect, useState } from "react";

const NIVELES = { simple: "Una firma", doble: "Dos firmas" };

export default function Aprobaciones() {
  const [lista, setLista] = useState(null);
  const [avisos, setAvisos] = useState({});

  const cargar = () => fetch("/cerebro/aprobaciones").then((r) => r.json()).then(setLista).catch(() => setLista([]));
  useEffect(() => { cargar(); }, []);

  async function decidir(id, aprobado) {
    const r = await fetch(`/cerebro/aprobaciones/${id}`, { method: "POST", body: JSON.stringify({ aprobado, canal: "panel" }) });
    const d = await r.json();
    if (!r.ok) return setAvisos((a) => ({ ...a, [id]: d.detail }));
    if (d.estado === "pendiente") setAvisos((a) => ({ ...a, [id]: "Aprobado por ti. Falta la segunda firma." }));
    else cargar();
  }

  return (
    <>
      <h1>Aprobaciones</h1>
      {lista === null && <p className="meta">Cargando…</p>}
      {lista?.length === 0 && <p className="meta">No hay nada esperando tu aprobación. Los agentes te avisarán aquí y en Jarvis.</p>}
      <div className="lista">
        {lista?.map((s) => (
          <article key={s.id} className="tarjeta">
            <header>
              <h2>{s.datos?.resumen || s.accion}</h2>
              <span className="nivel">{NIVELES[s.nivel]}</span>
            </header>
            <div className="meta">Lo propone {s.agente} ({s.departamento}) el {new Date(s.creado).toLocaleString("es-ES")}</div>
            <div className="botones">
              <button className="boton si" onClick={() => decidir(s.id, true)}>Aprobar</button>
              <button className="boton no" onClick={() => decidir(s.id, false)}>Rechazar</button>
            </div>
            {avisos[s.id] && <div className="aviso" role="status">{avisos[s.id]}</div>}
          </article>
        ))}
      </div>
    </>
  );
}
