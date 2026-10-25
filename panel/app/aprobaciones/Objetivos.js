"use client";
import { useCallback, useEffect, useState } from "react";

const fecha = (f) => (f ? new Date(f).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" }) : "");
const VACIO = { titulo: "", departamentos: [], operaciones: [], max_acciones: 20, dias: 7 };

// Objetivos permanentes: una firma de Dirección que cubre varias peticiones, con caducidad y tope. Lo reservado nunca entra.
export default function Objetivos() {
  const [d, setD] = useState(null);
  const [nuevo, setNuevo] = useState(VACIO);
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => fetch("/cerebro/objetivos").then(async (r) => {
    if (r.status === 403) return setD({ prohibido: true });
    setD(await r.json());
  }).catch(() => setD({ objetivos: [], operaciones: [], departamentos: [] })), []);
  useEffect(() => { cargar(); }, [cargar]);

  const alternar = (campo, v) => setNuevo((n) => ({ ...n, [campo]: n[campo].includes(v) ? n[campo].filter((x) => x !== v) : [...n[campo], v] }));

  async function crear(e) {
    e.preventDefault();
    setError("");
    setOcupado(true);
    try {
      const r = await fetch("/cerebro/objetivos", { method: "POST", body: JSON.stringify({ ...nuevo, max_acciones: Number(nuevo.max_acciones), dias: Number(nuevo.dias) }) });
      if (!r.ok) setError((await r.json().catch(() => ({}))).detail || "No se ha podido crear el objetivo.");
      else { setNuevo(VACIO); await cargar(); }
    } finally { setOcupado(false); }
  }

  async function revocar(o) {
    if (!window.confirm(`¿Revocar «${o.titulo}»? Dejará de cubrir acciones ahora mismo.`)) return;
    await fetch(`/cerebro/objetivos/${o.id}/revocar`, { method: "POST" });
    cargar();
  }

  if (!d) return <p className="meta">Cargando…</p>;
  if (d.prohibido) return <p className="meta">Solo Dirección gestiona los objetivos permanentes.</p>;
  return (
    <>
      <p className="meta">Un objetivo permanente es una firma que cubre varias peticiones: lo que encaje (departamento, operación) se ejecuta sin pedirte firma hasta que caduque o llegue al tope.
        Lo reservado (compromisos económicos o legales) siempre se firma una a una. Queda constancia de cada acción cubierta.</p>
      <form className="tarjeta ap-nuevo" onSubmit={crear}>
        <h3>Nuevo objetivo</h3>
        <label>Qué quieres conseguir
          <input value={nuevo.titulo} onChange={(e) => setNuevo({ ...nuevo, titulo: e.target.value })} placeholder="Reclamar las facturas vencidas de octubre" required />
        </label>
        <fieldset><legend>Departamentos</legend>
          {d.departamentos.map((x) => <label key={x} className="ap-check"><input type="checkbox" checked={nuevo.departamentos.includes(x)} onChange={() => alternar("departamentos", x)} /> {x}</label>)}
        </fieldset>
        <fieldset><legend>Qué se autoriza</legend>
          {d.operaciones.map((x) => <label key={x} className="ap-check"><input type="checkbox" checked={nuevo.operaciones.includes(x)} onChange={() => alternar("operaciones", x)} /> {x}</label>)}
        </fieldset>
        <div className="ap-numeros">
          <label>Máximo de acciones (hasta {d.limites?.max_acciones})
            <input type="number" min="1" max={d.limites?.max_acciones} value={nuevo.max_acciones} onChange={(e) => setNuevo({ ...nuevo, max_acciones: e.target.value })} />
          </label>
          <label>Vale durante (días, hasta {d.limites?.max_dias})
            <input type="number" min="1" max={d.limites?.max_dias} value={nuevo.dias} onChange={(e) => setNuevo({ ...nuevo, dias: e.target.value })} />
          </label>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="boton" disabled={ocupado}>Firmar objetivo</button>
      </form>
      {d.objetivos.length === 0 && <p className="meta">Todavía no hay objetivos permanentes.</p>}
      {d.objetivos.map((o) => (
        <article key={o.id} className="tarjeta ap-objetivo">
          <strong>{o.titulo}</strong>
          <span className="meta">{o.vigente ? "Vigente" : o.estado === "revocado" ? "Revocado" : o.usadas >= o.max_acciones ? "Tope alcanzado" : "Caducado"}
            {" · "}{o.usadas} de {o.max_acciones} acciones · hasta {fecha(o.caduca)}</span>
          <span className="meta">{o.departamentos.join(", ")} · {o.operaciones.join(", ")} · firmado por {o.creado_por}</span>
          {o.vigente && <button className="boton no" onClick={() => revocar(o)}>Revocar</button>}
        </article>
      ))}
    </>
  );
}
