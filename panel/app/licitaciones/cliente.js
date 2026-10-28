"use client";
import Link from "next/link";
import { estadoEtiqueta, fechaTexto, importeTexto, mensajeDeError } from "../../lib/licitaciones";

/** GET a la pasarela del motor. Lanza {status} si falla; una sesión caducada lleva al inicio de sesión como el resto del panel. */
export async function pedir(ruta) {
  const r = await fetch(`/licitaciones-api/${ruta}`, { cache: "no-store" });
  if (r.status === 401) {
    window.location.href = "/auth/login";
    throw { status: 401 };
  }
  if (!r.ok) throw { status: r.status };
  return r.json();
}

export const textoError = (e) => mensajeDeError(e?.status);

export function Fallo({ e }) {
  return <p role="alert" className="lic-error">{textoError(e)}</p>;
}

/** Una licitación en una lista: enlaza a su ficha. */
export function Item({ x }) {
  return (
    <li>
      <Link href={`/licitaciones/expedientes/${x.id}`} className="tarjeta tarjeta-enlace lic-item">
        <span className="titulo">{x.titulo || "(sin título)"}</span>
        <span className="meta">{[x.comprador?.nombre, x.expediente].filter(Boolean).join(" · ")}</span>
        <span className="lic-fila">
          <span className={`lic-etiqueta ${x.estado}`}>{estadoEtiqueta(x.estado)}</span>
          {x.importe && <span className="meta">{importeTexto(x.importe)}</span>}
          {x.plazo_presentacion && <span className="meta">Plazo: {fechaTexto(x.plazo_presentacion)}</span>}
          <span className="meta">Actualizada: {fechaTexto(x.actualizada_en)}</span>
        </span>
      </Link>
    </li>
  );
}
