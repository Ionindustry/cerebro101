"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { Actividad, Aprobaciones, Herramientas, Tarjeta } from "../../../componentes/Kpi";
import EstadoJev from "../../../componentes/EstadoJev";
import { formatearValor } from "../../../lib/kpi";

const PERIODOS = [7, 14, 30, 90];
const MALOS = new Set(["rechazadas", "pendientes", "decision"]);

export default function DashboardDepartamento({ params }) {
  const { id } = use(params);
  const [dias, setDias] = useState(30);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  const cargar = useCallback(() => fetch(`/cerebro/departamentos/${id}/kpis?dias=${dias}`)
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
      {!d && !error && <p className="meta">Cargando el dashboard…</p>}
      {d && (
        <>
          <header className="kp-cabecera">
            <div>
              <div className="director">Dashboard del departamento</div>
              <h1>{d.departamento.nombre}</h1>
              <div className="meta">{d.departamento.agentes} agentes · del {d.periodo.desde} al {d.periodo.hasta}</div>
            </div>
            <div className="kp-periodos" role="group" aria-label="Periodo">
              {PERIODOS.map((p) => <button key={p} aria-pressed={dias === p} onClick={() => setDias(p)}>{p} días</button>)}
            </div>
          </header>

          {d.grupos.map((g) => (
            <section className="kp-seccion" key={g.nombre}>
              <h2>{g.nombre}</h2>
              <div className="kp-rejilla">{g.kpis.map((k) => <Tarjeta key={k.id} k={k} />)}</div>
            </section>
          ))}

          <div className="kp-doble">
            <Actividad serie={d.serie} />
            <Herramientas lista={d.herramientas} />
          </div>

          <section className="kp-seccion">
            <h2>Rendimiento del equipo</h2>
            <div className="kp-rejilla">{d.rendimiento.map((k) => <Tarjeta key={k.id} k={k} malo={MALOS.has(k.id)} />)}</div>
          </section>
          <Aprobaciones a={d.aprobaciones} />

          <section className="kp-seccion">
            <h2>Equipo</h2>
            <div className="kp-tabla" role="table" aria-label="Agentes del departamento">
              <div className="kp-fila cab" role="row"><span>Agente</span><span>Peticiones</span><span>Usos</span><span>Éxito</span><span>Propuestas</span><span>Esperan firma</span></div>
              {d.equipo.map((a) => (
                <Link key={a.id} className="kp-fila" role="row" href={`/agentes/${a.id}`}>
                  <span><b>{a.nombre}</b>{a.director ? <small> · dirige</small> : null}<span className="meta" style={{ display: "block" }}>{a.subarea}</span></span>
                  <span>{formatearValor(a.peticiones)}</span><span>{formatearValor(a.usos)}</span><span>{a.exito === null ? "—" : `${a.exito} %`}</span>
                  <span>{formatearValor(a.propuestas)}</span><span>{a.pendientes || "—"}</span>
                </Link>
              ))}
            </div>
          </section>
          <EstadoJev />
        </>
      )}
    </>
  );
}
