"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CATEGORIAS, NIVELES, hoyIndicadores, hoyResumen, hrefSeguro } from "../../lib/hoy";
import { Barras, Cifra } from "../licitaciones/buscar/Dashboard";

// «Qué hacer hoy»: lo que necesita atención de quien abre Jarvis, en una sola lista ordenada por urgencia. Solo lee: cada elemento lleva a la pantalla donde se resuelve.
export default function Hoy() {
  const [d, setD] = useState(undefined);       // undefined = cargando; null = error
  const cargar = useCallback(() => fetch("/cerebro/hoy").then((r) => { if (r.status === 401) { window.location.href = "/auth/login"; return null; } if (!r.ok) throw new Error(); return r.json(); }).then(setD).catch(() => setD(null)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 60000); return () => clearInterval(t); }, [cargar]);
  const [pestana, setPestana] = useState("hoy");
  const [archivo, setArchivo] = useState(undefined);   // undefined = sin cargar; null = error
  const [fallo, setFallo] = useState("");
  const cargarArchivo = useCallback(() => fetch("/cerebro/hoy/archivo").then((x) => { if (!x.ok) throw new Error(); return x.json(); }).then((j) => setArchivo(j.items)).catch(() => setArchivo(null)), []);
  useEffect(() => { if (pestana === "archivo") cargarArchivo(); }, [pestana, cargarArchivo]);
  // Archivar y recuperar: lo vencido que ya has visto sale de la lista de hoy y queda en «Archivo» (solo para ti).
  const mover = async (accion, clave) => {
    setFallo("");
    try {
      const x = await fetch(`/cerebro/hoy/${accion}`, { method: "POST", body: JSON.stringify({ clave }) });
      if (!x.ok) throw new Error();
      await Promise.all([cargar(), pestana === "archivo" ? cargarArchivo() : null]);
    } catch { setFallo("No se ha podido completar. Actualiza la lista e inténtalo de nuevo."); }
  };
  const r = hoyResumen(d);
  const ind = hoyIndicadores(d);
  const nArchivo = d?.archivados || 0;
  return (
    <div className="lic">
      <div className="lic-fila">
        <h1>Qué hacer hoy</h1>
        <button className="boton no" onClick={cargar}>Actualizar</button>
      </div>
      <div className="ap-pestanas" role="tablist">
        <button role="tab" aria-selected={pestana === "hoy"} onClick={() => setPestana("hoy")}>Hoy</button>
        <button role="tab" aria-selected={pestana === "archivo"} onClick={() => setPestana("archivo")}>Archivo{nArchivo ? <span className="contador">{nArchivo}</span> : null}</button>
      </div>
      {fallo && <p role="alert" className="lic-error">{fallo}</p>}
      {pestana === "archivo" ? (
        <section className="lic" aria-label="Archivo">
          <p className="meta">Lo vencido que has archivado. Es solo tuyo y puedes recuperarlo cuando quieras.</p>
          {archivo === undefined && <p className="meta" aria-busy="true">Cargando…</p>}
          {archivo === null && <p role="alert" className="lic-error">No se ha podido cargar el archivo.</p>}
          {archivo && archivo.length === 0 && <p className="meta">No hay nada archivado.</p>}
          {archivo && archivo.length > 0 && (
            <ul className="lic-lista">
              {archivo.map((i) => {
                const href = hrefSeguro(i.href);
                return (
                  <li key={i.clave} className="tarjeta lic-item">
                    <span className="lic-fila"><span className="titulo">{href ? <Link href={href}>{i.titulo}</Link> : i.titulo}</span><span className="meta">{CATEGORIAS[i.categoria] || i.categoria}</span></span>
                    {i.detalle && <span className="meta">{i.detalle}</span>}
                    <span className="lic-fila"><span className="meta">Archivado el {new Date(i.archivado).toLocaleDateString("es-ES")}</span><button className="boton no" onClick={() => mover("desarchivar", i.clave)}>Recuperar</button></span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ) : (<>
      {d === undefined ? <p className="meta" aria-busy="true">Cargando…</p> : <p role="status"><strong>{r.titular}</strong></p>}
      {d && ind.total > 0 && (
        <>
          <div className="lic-cifras">
            <Cifra titulo="Urgente" valor={ind.urgentes} nota={ind.urgentes ? "hazlo hoy" : "nada urgente"} />
            <Cifra titulo="Hay que mirarlo" valor={ind.porMirar} />
            <Cifra titulo="Para tu información" valor={ind.info} />
            <Cifra titulo="Total" valor={ind.total} />
          </div>
          <div className="lic-graficos">
            <Barras titulo="Por urgencia" grupos={ind.porNivel} etiqueta={(v) => NIVELES[v]?.titulo || v} />
            <Barras titulo="Por área" grupos={ind.porCategoria} etiqueta={(v) => CATEGORIAS[v] || v} />
          </div>
        </>
      )}
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
              return (
                <li key={`${i.categoria}-${k}`}>
                  {href ? <Link href={href} className="tarjeta tarjeta-enlace lic-item">{cuerpo}</Link> : <div className="tarjeta lic-item">{cuerpo}</div>}
                  {i.archivable && <button className="boton no" onClick={() => mover("archivar", i.clave)}>Archivar</button>}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      </>)}
    </div>
  );
}
