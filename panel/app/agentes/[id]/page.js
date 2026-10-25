"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { Actividad, Aprobaciones, Herramientas, Tarjeta } from "../../../componentes/Kpi";

const APROBACION = { libre: "Actúa solo", simple: "Pide tu firma", doble: "Pide tu firma" };
const PERIODOS = [7, 14, 30, 90];
// En estos KPI subir es malo: el color de la variación no debe parecer una buena noticia
const MALOS = new Set(["rechazadas", "pendientes", "decision"]);

export default function PanelAgente({ params }) {
  const { id } = use(params);
  const [dias, setDias] = useState(30);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  const cargar = useCallback(() => fetch(`/cerebro/agentes/${id}/kpis?dias=${dias}`)
    .then(async (r) => {
      if (r.status === 401) { window.location.href = "/auth/login"; return; }
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { setError({ estado: r.status, texto: j.detail || "No se han podido cargar los KPI" }); return; }
      setD(j); setError(null);
    }).catch(() => setError({ estado: 0, texto: "No hay conexión con el Cerebro" })), [id, dias]);
  useEffect(() => { setD(null); cargar(); const t = setInterval(cargar, 30000); return () => clearInterval(t); }, [cargar]);

  return (
    <>
      <Link href="/agentes" className="kp-atras">← Agentes</Link>
      {error && !d && <div className="of-demo" role="alert">{error.texto}</div>}
      {!d && !error && <p className="meta">Cargando los KPI…</p>}
      {d && (
        <>
          <header className="kp-cabecera">
            <div>
              {d.agente.director && <div className="director">Dirige su departamento</div>}
              <h1>{d.agente.nombre}</h1>
              <div className="meta">{d.agente.subarea} · {d.agente.departamento} · {APROBACION[d.agente.aprobacion]}</div>
              <p className="kp-tareas">{d.agente.tareas}</p>
              <div className="of-tags">{d.agente.herramientas.map((h) => <span key={h}>{h}</span>)}</div>
            </div>
            <div className="kp-periodos" role="group" aria-label="Periodo">
              {PERIODOS.map((p) => <button key={p} aria-pressed={dias === p} onClick={() => setDias(p)}>{p} días</button>)}
              <Link className="of-boton" href="/oficina">Ver en la oficina</Link>
            </div>
          </header>

          <section className="kp-seccion">
            <h2>KPI del cargo</h2>
            <div className="kp-rejilla">{d.cargo.map((k) => <Tarjeta key={k.id} k={k} />)}</div>
            {d.cargo.every((k) => k.estado === "no_disponible") && <p className="meta">Ningún dato del ERP está disponible ahora mismo; los demás indicadores sí.</p>}
          </section>

          <div className="kp-doble">
            <Actividad serie={d.serie} />
            <Herramientas lista={d.herramientas} />
          </div>

          <section className="kp-seccion">
            <h2>Rendimiento del agente <small>· del {d.periodo.desde} al {d.periodo.hasta}</small></h2>
            <div className="kp-rejilla">{d.rendimiento.map((k) => <Tarjeta key={k.id} k={k} malo={MALOS.has(k.id)} />)}</div>
          </section>
          <Aprobaciones a={d.aprobaciones} />
        </>
      )}
    </>
  );
}
