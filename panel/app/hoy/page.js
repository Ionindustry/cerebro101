"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CATEGORIAS, hoyResumen, hrefSeguro } from "../../lib/hoy";

// «Qué hacer hoy»: lo que necesita atención de quien abre Jarvis, en una sola lista ordenada por urgencia. Solo lee: cada elemento lleva a la pantalla donde se resuelve.
export default function Hoy() {
  const [d, setD] = useState(undefined);       // undefined = cargando; null = error
  const cargar = useCallback(() => fetch("/cerebro/hoy").then((r) => { if (r.status === 401) { window.location.href = "/auth/login"; return null; } if (!r.ok) throw new Error(); return r.json(); }).then(setD).catch(() => setD(null)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 60000); return () => clearInterval(t); }, [cargar]);
  const r = hoyResumen(d);
  return (
    <div className="lic">
      <div className="lic-fila">
        <h1>Qué hacer hoy</h1>
        <button className="boton no" onClick={cargar}>Actualizar</button>
      </div>
      {d === undefined ? <p className="meta" aria-busy="true">Cargando…</p> : <p role="status"><strong>{r.titular}</strong></p>}
      {r.avisos.map((a) => <p key={a} role="status" className="lic-aviso">{a}</p>)}
      {r.grupos.map((g) => (
        <section key={g.nivel} className="lic" aria-label={g.titulo}>
          <h2><span className={`lic-etiqueta ${g.clase}`}>{g.titulo}</span> <span className="meta">· {g.items.length}</span></h2>
          <ul className="lic-lista">
            {g.items.map((i, k) => {
              const href = hrefSeguro(i.href);
              const cuerpo = (
                <>
                  <span className="lic-fila"><span className="titulo">{i.titulo}</span><span className="meta">{CATEGORIAS[i.categoria] || i.categoria}</span></span>
                  {i.detalle && <span className="meta">{i.detalle}</span>}
                </>
              );
              return <li key={`${i.categoria}-${k}`}>{href ? <Link href={href} className="tarjeta tarjeta-enlace lic-item">{cuerpo}</Link> : <div className="tarjeta lic-item">{cuerpo}</div>}</li>;
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
