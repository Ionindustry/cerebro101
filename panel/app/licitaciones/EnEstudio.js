"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { avisoEstadoMotor, claseDePlazo, diasTexto, encajeClase, enEstudioOrdenadas, fechaTexto, hrefEnEstudio, importeTexto } from "../../lib/licitaciones";
import { pedirCerebro } from "./cliente";

/** Las licitaciones que se están estudiando, con las que cierran antes primero. Cada una enlaza a su ficha (pliegos, requisitos, oferta, encargos…). Solo para Dirección y Licitaciones: sin acceso, no aparece. */
export default function EnEstudio() {
  const [items, setItems] = useState(undefined);       // undefined = cargando; null = sin acceso o error
  useEffect(() => { pedirCerebro("licitaciones/embudo?estado=en_estudio&limite=100").then((r) => setItems(r.items)).catch(() => setItems(null)); }, []);
  if (items === null) return null;
  const lista = enEstudioOrdenadas(items);
  return (
    <section className="tarjeta" aria-labelledby="lic-estudio-t">
      <header>
        <h3 id="lic-estudio-t">En estudio{items !== undefined ? ` · ${lista.length}` : ""}</h3>
        <Link href="/licitaciones/embudo" className="lic-vuelve">Ver el embudo completo</Link>
      </header>
      {items === undefined && <p className="meta" aria-busy="true">Cargando…</p>}
      {items !== undefined && lista.length === 0 && <p className="meta">No hay ninguna licitación en estudio. Pasa una a «en estudio» desde su ficha o desde el embudo.</p>}
      {lista.length > 0 && (
        <ul className="lic-lista">
          {lista.map((x) => (
            <li key={x.id}>
              <Link href={hrefEnEstudio(x)} className="tarjeta tarjeta-enlace lic-item">
                <span className="lic-fila">
                  <span className={`lic-encaje ${encajeClase(x.encaje)}`} title="Encaje con 101.cat (0–100)">{x.encaje ?? "—"}</span>
                  <span className="titulo">{x.titulo}</span>
                </span>
                <span className="meta">{[x.organismo, x.expediente].filter(Boolean).join(" · ")}</span>
                <span className="lic-fila">
                  {x.fecha_limite && <span className={`lic-etiqueta ${claseDePlazo(x.dias)}`}>{diasTexto(x.dias)}</span>}
                  {x.fecha_limite && <span className="meta">Plazo: {fechaTexto(x.fecha_limite)}</span>}
                  {x.importe != null && <span className="meta">{importeTexto({ valor: String(x.importe), moneda: "EUR", impuestos: "sin_iva" })}</span>}
                  {avisoEstadoMotor(x.estado_motor) && <span className="lic-etiqueta aviso">{avisoEstadoMotor(x.estado_motor)}</span>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
