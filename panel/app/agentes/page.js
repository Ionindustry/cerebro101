"use client";
import { useEffect, useState } from "react";

const APROBACION = { libre: "Actúa solo", simple: "Pide una firma", doble: "Pide dos firmas" };

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
      <div className="filtros">
        <button aria-pressed={!filtro} onClick={() => setFiltro(null)}>Todos</button>
        {Object.entries(deps).map(([id, d]) => (
          <button key={id} aria-pressed={filtro === id} onClick={() => setFiltro(id)}>{d.nombre}</button>
        ))}
      </div>
      <div className="agentes">
        {visibles.map((a) => (
          <article key={a.id} className="tarjeta">
            {a.director && <div className="director">Dirige {deps[a.departamento]?.nombre}</div>}
            <h2>{a.nombre}</h2>
            <div className="meta">{a.subarea}</div>
            <p>{a.tareas}</p>
            <p>{APROBACION[a.aprobacion]}.{a.horario ? " Trabaja también de forma programada." : ""}</p>
          </article>
        ))}
      </div>
    </>
  );
}
