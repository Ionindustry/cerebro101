"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ORDENES, comandoAutorizarRanking, estadoDominio, ventasTexto } from "../../lib/fabricantes";
import { Fallo, pedirCerebro } from "../licitaciones/cliente";

/** Los 10 fabricantes principales de cada sector de seguridad, con ventas y plantilla publicadas. Es una referencia (no el ranking mundial exacto) y sirve también para decidir qué dominios autorizar para fichas. */
export default function Fabricantes() {
  const [sector, setSector] = useState("");
  const [orden, setOrden] = useState("seleccion");
  const [d, setD] = useState(undefined);
  const [error, setError] = useState(null);

  const cargar = useCallback(async () => {
    setError(null);
    try { setD(await pedirCerebro(`licitaciones/fabricantes/ranking?orden=${orden}${sector ? `&sector=${encodeURIComponent(sector)}` : ""}`)); }
    catch (e) { setError(e); setD((x) => (x === undefined ? null : x)); }
  }, [sector, orden]);
  useEffect(() => { cargar(); }, [cargar]);

  const comando = d ? comandoAutorizarRanking(d.sectores) : "";
  return (
    <main className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones/fichas">← Fichas técnicas</Link></p>
      <h1>Fabricantes por sector</h1>
      {d?.aviso && <p className="meta">{d.aviso}</p>}
      <div className="lic-fila">
        <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
          <option value="">Todos los sectores</option>
          {(d?.todos_los_sectores || []).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={orden} onChange={(e) => setOrden(e.target.value)} aria-label="Orden">{ORDENES.map((o) => <option key={o.id} value={o.id}>{o.nombre}</option>)}</select>
      </div>
      {error && <Fallo e={error} />}
      {d === undefined && <p>Cargando…</p>}
      {comando && <p className="meta">Para autorizar los dominios comprobados que faltan, en Ubuntu: <code>{comando}</code></p>}
      {d?.sectores?.map((s) => (
        <section className="tarjeta" key={s.sector}>
          <h2>{s.sector} <span className="meta">({s.con_ventas} de {s.fabricantes.length} con cifra de ventas)</span></h2>
          <ol>{s.fabricantes.map((f) => (
            <li key={f.fabricante}>
              <strong>{f.fabricante}</strong> — ventas de seguridad: {ventasTexto(f.ventas_musd)}
              {f.otros_ingresos ? ` · otros ingresos: ${f.otros_ingresos}` : ""}{f.empleados ? ` · empleados: ${f.empleados}` : ""}
              {" · "}<span className={f.autorizado || f.comprobado ? "" : "aviso"}>dominio {estadoDominio(f)}</span>
              {f.sin_validar && <span className="aviso"> · datos sin validar</span>}
              {f.nota && f.nota !== "Sin indicación especial; revisar perímetro de ingresos." && <div className="meta">{f.nota}</div>}
            </li>))}</ol>
        </section>
      ))}
    </main>
  );
}
