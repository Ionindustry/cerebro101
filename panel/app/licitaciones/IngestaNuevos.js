"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { consultasIngesta, totalIngestaTexto, ventanasIngesta } from "../../lib/licitaciones";
import { pedir } from "./cliente";

/** Indicador de ingesta: cuántos concursos han entrado en el motor hoy, en 24 h y en 7 días (nuevos, los que siguen abiertos y los que han cambiado). Solo lee; se refresca solo cada 2 minutos y tras una actualización manual. */
export default function IngestaNuevos({ version = 0 }) {
  const [filas, setFilas] = useState(null);
  const [fallo, setFallo] = useState(false);
  useEffect(() => {
    let vivo = true;
    const leer = async () => {
      try {
        const out = await Promise.all(ventanasIngesta().map(async (v) => {
          const q = consultasIngesta(v.desde);
          const [nuevas, abiertas, novedades] = await Promise.all([pedir(q.nuevas), pedir(q.abiertas), pedir(q.novedades)]);
          return { ...v, nuevas, abiertas, novedades };
        }));
        if (vivo) { setFilas(out); setFallo(false); }
      } catch { if (vivo) setFallo(true); }
    };
    leer();
    const t = setInterval(leer, 120000);
    return () => { vivo = false; clearInterval(t); };
  }, [version]);
  return (
    <section className="tarjeta" aria-labelledby="lic-ing-t">
      <header>
        <h2 id="lic-ing-t">Concursos ingeridos</h2>
        <Link href="/licitaciones/buscar?orden=actualizacion" className="lic-vuelve">Ver las últimas</Link>
      </header>
      {fallo && !filas && <p className="meta" role="status">No se ha podido contar lo ingerido ahora mismo.</p>}
      {!filas && !fallo && <p className="meta" aria-busy="true">Contando…</p>}
      {filas && (
        <table className="lic-tabla">
          <thead><tr><th scope="col"></th><th scope="col">Nuevos</th><th scope="col">…aún abiertos</th><th scope="col">Con novedad</th></tr></thead>
          <tbody>
            {filas.map((f) => (
              <tr key={f.clave}>
                <th scope="row">{f.etiqueta}</th>
                <td><strong>{totalIngestaTexto(f.nuevas)}</strong></td>
                <td>{totalIngestaTexto(f.abiertas)}</td>
                <td>{totalIngestaTexto(f.novedades)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="meta">Nuevos = publicados en esa ventana. Con novedad = nuevos o con una versión nueva (cambio de plazo, adjudicación…).</p>
    </section>
  );
}
