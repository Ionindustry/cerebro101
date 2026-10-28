"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { antiguedadTexto, estadoMotor, ESTADOS_EMBUDO, fechaCivilTexto, nombreFuente, sinLeerTexto, tasaExitoTexto, totalesTexto } from "../../lib/licitaciones";
import { Fallo, Item, Oportunidad, pedir, pedirCerebro } from "./cliente";

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

// Resumen de las 16:00: solo se muestra a quien lo puede ver (Dirección y Licitaciones); para los demás, la tarjeta no aparece.
function ResumenDelDia() {
  const [r, setR] = useState(null);
  useEffect(() => { pedirCerebro("licitaciones/resumenes/ultimo").then(setR).catch(() => setR(null)); }, []);
  if (!r) return null;
  const c = r.contenido;
  return (
    <section className="tarjeta" aria-labelledby="lic-res-t">
      <header>
        <h2 id="lic-res-t">Resumen de las 16:00 · {fechaCivilTexto(r.fecha)}</h2>
        <Link href="/licitaciones/resumen" className="lic-vuelve">Ver el resumen</Link>
      </header>
      {c.estado !== "ok" ? <p role="status" className="lic-aviso">{c.aviso}</p> : (
        <>
          <p className="meta">{totalesTexto(c.totales)}</p>
          {c.aviso && <p role="status" className="lic-aviso">{c.aviso}</p>}
          {c.oportunidades.length > 0 && <ul className="lic-lista">{c.oportunidades.slice(0, 3).map((x) => <Oportunidad key={x.id} x={x} />)}</ul>}
        </>
      )}
    </section>
  );
}

// Embudo propio: lo que 101.cat estudia, presenta, gana o pierde. Solo para quien puede verlo (Dirección y Licitaciones).
function EmbudoPropio() {
  const [r, setR] = useState(null);
  useEffect(() => { pedirCerebro("licitaciones/embudo/resumen?dias=30").then(setR).catch(() => setR(null)); }, []);
  if (!r) return null;
  return (
    <section className="tarjeta" aria-labelledby="lic-emb-t">
      <header>
        <h2 id="lic-emb-t">Embudo propio · 30 días</h2>
        <Link href="/licitaciones/embudo" className="lic-vuelve">Ver el embudo</Link>
      </header>
      <p className="meta">{ESTADOS_EMBUDO.map(([k, n]) => `${n}: ${r.por_estado[k] ?? 0}`).join(" · ")}</p>
      <p className="meta">Tasa de éxito: {tasaExitoTexto(r.tasa_exito)}</p>
    </section>
  );
}

// Avisos de las alertas guardadas: solo para quien tiene acceso; si no hay alertas ni avisos, la tarjeta no ocupa sitio.
function AvisosDeAlertas() {
  const [v, setV] = useState(null);
  useEffect(() => { pedirCerebro("licitaciones/avisos?no_leidos=true&limite=3").then(setV).catch(() => setV(null)); }, []);
  if (!v) return null;
  return (
    <section className="tarjeta" aria-labelledby="lic-avi-t">
      <header>
        <h2 id="lic-avi-t">Alertas · {sinLeerTexto(v.sin_leer)}</h2>
        <Link href="/licitaciones/alertas" className="lic-vuelve">{v.sin_leer > 0 ? "Ver los avisos" : "Gestionar alertas"}</Link>
      </header>
      {v.items.length > 0 && <ul className="lic-lista">{v.items.map((x) => <li key={x.id} className="meta">{x.titulo} <span className="lic-etiqueta">Alerta «{x.alerta}»</span></li>)}</ul>}
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
      <p className="lic-fila">
        <Link href="/licitaciones/competencia" className="boton no">Competencia: quién gana en cada mercado</Link>
        <Link href="/licitaciones/vencen" className="boton no">Contratos que vencen: cuándo vuelve a salir</Link>
      </p>
      <ResumenDelDia />
      <AvisosDeAlertas />
      <EmbudoPropio />
      <EstadoDelMotor />
      <Novedades />
    </div>
  );
}
