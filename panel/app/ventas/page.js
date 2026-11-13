"use client";
import { useCallback, useEffect, useState } from "react";
import { PERIODOS_VENTAS, TOPS, importeVentas, rankingTexto, resumenTipo, unidadesTexto } from "../../lib/ventas";
import { Fallo, pedirCerebro } from "../licitaciones/cliente";

/** Los artículos y fabricantes que más venden en cada tipo (CCTV, control de accesos, intrusión…), de los pedidos de venta confirmados del ERP. Solo Dirección. */
export default function Ventas() {
  const [dias, setDias] = useState(365);
  const [top, setTop] = useState(10);
  const [d, setD] = useState(undefined);        // undefined = cargando; null = sin acceso
  const [error, setError] = useState(null);
  const [copiado, setCopiado] = useState(false);

  const cargar = useCallback(async () => {
    setD(undefined); setError(null);
    try { setD(await pedirCerebro(`ventas/ranking?dias=${dias}&top=${top}`)); }
    catch (e) { setD(null); if (e.status !== 403) setError(e); }
  }, [dias, top]);
  useEffect(() => { cargar(); }, [cargar]);

  const copiar = async () => {
    try { await navigator.clipboard.writeText(rankingTexto(d)); setCopiado(true); setTimeout(() => setCopiado(false), 2500); } catch { setError({ status: 0, detalle: "No se ha podido copiar" }); }
  };

  return (
    <main className="lic">
      <h1>Ventas por tipo</h1>
      <p className="meta">Los {top} artículos y fabricantes que más venden en cada tipo, por importe neto de los pedidos de venta confirmados. Los tipos se definen en config/tipos_producto.yaml.</p>
      <div className="lic-fila">
        <select value={dias} onChange={(e) => setDias(Number(e.target.value))} aria-label="Periodo">{PERIODOS_VENTAS.map((p) => <option key={p.dias} value={p.dias}>{p.nombre}</option>)}</select>
        <select value={top} onChange={(e) => setTop(Number(e.target.value))} aria-label="Cuántos mostrar">{TOPS.map((n) => <option key={n} value={n}>Top {n}</option>)}</select>
        <button className="boton no" onClick={copiar} disabled={!d?.tipos?.length}>{copiado ? "Copiado" : "Copiar como texto"}</button>
      </div>
      {error && <Fallo e={error} />}
      {d === undefined && <p>Cargando…</p>}
      {d === null && !error && <p className="aviso">Las ventas de la empresa las ve solo Dirección.</p>}
      {d && (<>
        <p className="meta">Del {d.desde} al {d.hasta} (excluido) · {d.lineas} líneas · total {importeVentas(d.total)}</p>
        {d.aviso && <p className="aviso" role="status">{d.aviso}</p>}
        {d.tipos.length === 0 && <p>No hay pedidos de venta confirmados en el periodo.</p>}
        {d.tipos.map((t) => (
          <section className="tarjeta" key={t.tipo}>
            <h2>{resumenTipo(t)}</h2>
            <div className="lic-fila">
              <div>
                <h3>Artículos</h3>
                <ol>{t.articulos.map((a) => <li key={a.codigo}>{a.nombre} <span className="meta">({a.codigo}{a.marca ? ` · ${a.marca}` : ""})</span> — {importeVentas(a.importe)} · {unidadesTexto(a.unidades)} uds</li>)}</ol>
              </div>
              <div>
                <h3>Fabricantes</h3>
                <ol>{t.fabricantes.map((m) => <li key={m.nombre}>{m.nombre} — {importeVentas(m.importe)}</li>)}</ol>
              </div>
            </div>
          </section>
        ))}
      </>)}
    </main>
  );
}
