"use client";
import Link from "next/link";
import EstadoJev from "../../componentes/EstadoJev";
import { useEffect, useState } from "react";

const APROBACION = { libre: "Actúa solo", simple: "Pide tu firma", doble: "Pide tu firma (solo en el panel)" };

export default function Agentes() {
  const [deps, setDeps] = useState({});
  const [agentes, setAgentes] = useState([]);
  const [filtro, setFiltro] = useState(null);

  useEffect(() => {
    fetch("/cerebro/departamentos").then((r) => r.json()).then(setDeps).catch(() => {});
    fetch("/cerebro/agentes").then((r) => r.json()).then(setAgentes).catch(() => {});
  }, []);

  const visibles = filtro ? agentes.filter((a) => a.departamento === filtro) : agentes;
  return (
    <>
      <h1>{visibles.length} agentes</h1>
      <EstadoJev />
      <div className="filtros">
        <button aria-pressed={!filtro} onClick={() => setFiltro(null)}>Todos</button>
        {Object.entries(deps).map(([id, d]) => (
          <button key={id} aria-pressed={filtro === id} onClick={() => setFiltro(id)}>{d.nombre}</button>
        ))}
      </div>
      {filtro && <Link className="of-boton dep-link" href={`/departamentos/${filtro}`}>Dashboard de {deps[filtro]?.nombre} →</Link>}
      <div className="agentes">
        {visibles.map((a) => (
          <Link key={a.id} href={`/agentes/${a.id}`} className="tarjeta tarjeta-enlace" aria-label={`Ver los KPI de ${a.nombre}`}>
            {a.director && <div className="director">Dirige {deps[a.departamento]?.nombre}</div>}
            <h2>{a.nombre}</h2>
            <div className="meta">{a.subarea}</div>
            <p>{a.tareas}</p>
            <p>{APROBACION[a.aprobacion]}.{a.horario ? " Trabaja también de forma programada." : ""}</p>
            <span className="ver-kpi">Ver KPI →</span>
          </Link>
        ))}
      </div>
    </>
  );
}
