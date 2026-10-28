"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { antiguedadTexto, estadoMotor, nombreFuente } from "../../lib/licitaciones";
import { Fallo, Item, pedir } from "./cliente";

function EstadoDelMotor() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { pedir("ops/status").then(setD).catch(setError); }, []);
  if (error) return <section className="tarjeta"><h2>Estado del motor</h2><Fallo e={error} /></section>;
  if (!d) return <section className="tarjeta" aria-busy="true"><h2>Estado del motor</h2><p className="meta">Consultando…</p></section>;
  const e = estadoMotor(d.estado);
  return (
    <section className="tarjeta" aria-labelledby="lic-estado-t">
      <header>
        <h2 id="lic-estado-t">Estado del motor</h2>
        <span className={`lic-estado ${e.clase}`}>{e.texto}</span>
      </header>
      {d.motivos?.length > 0 && <ul className="meta">{d.motivos.map((m, i) => <li key={i}>{m.mensaje}</li>)}</ul>}
      <ul className="lic-fuentes">
        {(d.fuentes || []).map((f) => (
          <li key={f.fuente}>
            <strong>{nombreFuente(f.fuente)}</strong> · última ingesta completa {antiguedadTexto(f.antiguedad_s)} · {new Intl.NumberFormat("es-ES").format(f.expedientes ?? 0)} expedientes
          </li>
        ))}
        {(d.fuentes || []).length === 0 && <li className="meta">Todavía no hay fuentes ingeridas.</li>}
      </ul>
    </section>
  );
}

function Novedades() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { pedir("tenders?orden=actualizacion&limit=8").then(setD).catch(setError); }, []);
  return (
    <section aria-labelledby="lic-nov-t" className="lic">
      <div className="lic-fila"><h2 id="lic-nov-t">Últimas novedades</h2><Link href="/licitaciones/buscar" className="lic-vuelve">Ver todas</Link></div>
      {error && <Fallo e={error} />}
      {!d && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {d && d.items.length === 0 && <p className="meta">Todavía no hay licitaciones. El ingestor las irá cargando.</p>}
      {d && d.items.length > 0 && <ul className="lic-lista">{d.items.map((x) => <Item key={x.id} x={x} />)}</ul>}
    </section>
  );
}

export default function Licitaciones() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const buscar = (ev) => {
    ev.preventDefault();
    router.push(q.trim().length >= 2 ? `/licitaciones/buscar?q=${encodeURIComponent(q.trim())}` : "/licitaciones/buscar");
  };
  return (
    <div className="lic">
      <h1>Licitaciones</h1>
      <form className="lic-busca" onSubmit={buscar} role="search">
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por texto: videovigilancia, software, mantenimiento…" aria-label="Buscar licitaciones" maxLength={200} />
        <button className="boton si" type="submit">Buscar</button>
      </form>
      <EstadoDelMotor />
      <Novedades />
    </div>
  );
}
