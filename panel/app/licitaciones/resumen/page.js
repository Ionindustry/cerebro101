"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fechaCivilTexto, fechaTexto, mensajeResumen, ORIGEN_RESUMEN, totalesTexto, urlSegura, ventanaTexto } from "../../../lib/licitaciones";
import { Item, Oportunidad, pedirCerebro } from "../cliente";

const Aviso = ({ children }) => <p role="status" className="lic-aviso">{children}</p>;

function Lista({ titulo, items, vacio, total }) {
  return (
    <section className="lic" aria-label={titulo}>
      <h2>{titulo}{total > items.length ? <span className="meta"> · se detallan {items.length} de {total}</span> : null}</h2>
      {items.length === 0 ? <p className="meta">{vacio}</p> : <ul className="lic-lista">{items.map((x) => <Otra key={x.id} x={x} />)}</ul>}
    </section>
  );
}

// Adjudicaciones y anulaciones: misma tarjeta que el listado general (sin plazo ni encaje destacado)
const Otra = ({ x }) => <Item x={{ ...x, comprador: { nombre: x.comprador }, actualizada_en: null }} />;

export default function Resumen() {
  const [lista, setLista] = useState([]);
  const [actual, setActual] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [generando, setGenerando] = useState(false);

  const abrir = useCallback(async (id) => {
    setCargando(true); setError(null);
    try { setActual(await pedirCerebro(id ? `licitaciones/resumenes/${id}` : "licitaciones/resumenes/ultimo")); }
    catch (e) { setActual(null); setError(e); }
    finally { setCargando(false); }
  }, []);

  const recargar = useCallback(async () => {
    try { setLista(await pedirCerebro("licitaciones/resumenes?limite=14")); } catch { setLista([]); }
  }, []);

  useEffect(() => { abrir(null); recargar(); }, [abrir, recargar]);

  const generar = async () => {
    setGenerando(true); setError(null);
    try { setActual(await pedirCerebro("licitaciones/resumenes", { method: "POST" })); await recargar(); }
    catch (e) { setError(e); }
    finally { setGenerando(false); }
  };

  const c = actual?.contenido;
  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <div className="lic-fila">
        <h1>Resumen de licitaciones</h1>
        <button className="boton no" onClick={generar} disabled={generando} title="Genera el resumen de las últimas 24 horas ahora">
          {generando ? "Generando…" : "Generar ahora"}
        </button>
      </div>

      {error && <p role="alert" className="lic-error">{mensajeResumen(error.status)}</p>}
      {cargando && !actual && !error && <p className="meta" aria-busy="true">Cargando…</p>}

      {actual && c && (
        <>
          <section className="tarjeta" aria-label="Periodo">
            <header>
              <h2>{fechaCivilTexto(actual.fecha)}</h2>
              <span className="meta">{ORIGEN_RESUMEN[actual.origen] || actual.origen}</span>
            </header>
            <p className="meta">Novedades publicadas {ventanaTexto(c.ventana)} (hora de Madrid) · generado el {fechaTexto(actual.generado)}</p>
            {c.estado === "ok" && <p>{totalesTexto(c.totales)}{c.totales?.fuera_de_importe ? ` · ${c.totales.fuera_de_importe} por encima del límite de importe (no se detallan)` : ""}</p>}
            {c.aviso && <Aviso>{c.aviso}</Aviso>}
          </section>

          {c.estado === "ok" && (
            <>
              <section className="lic" aria-label="Oportunidades">
                <h2>Oportunidades{c.totales.oportunidades > c.oportunidades.length ? <span className="meta"> · se detallan {c.oportunidades.length} de {c.totales.oportunidades}</span> : null}</h2>
                <p className="meta">Ordenadas por encaje con 101.cat (0–100): CPV, zona, importe, plazo y procedimiento.</p>
                {c.oportunidades.length === 0 ? <p className="meta">Ninguna novedad abierta en tus CPV en este periodo.</p>
                  : <ul className="lic-lista">{c.oportunidades.map((x) => <Oportunidad key={x.id} x={x} />)}</ul>}
              </section>
              <Lista titulo="Adjudicaciones" items={c.adjudicaciones} total={c.totales.adjudicaciones} vacio="Ninguna adjudicación nueva en tus CPV." />
              <Lista titulo="Anuladas" items={c.anuladas} total={c.totales.anuladas} vacio="Ninguna anulación." />
            </>
          )}
        </>
      )}

      {lista.length > 1 && (
        <section className="tarjeta" aria-label="Resúmenes anteriores">
          <h2>Anteriores</h2>
          <ul className="lic-historial">
            {lista.map((r) => (
              <li key={r.id}>
                <button className="lic-enlace" onClick={() => abrir(r.id)} aria-current={actual?.id === r.id ? "true" : undefined}>
                  {fechaCivilTexto(r.fecha)} <span className="meta">· {ORIGEN_RESUMEN[r.origen] || r.origen}{r.estado === "sin_datos" ? " · sin datos" : ` · ${totalesTexto(r.totales)}`}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
