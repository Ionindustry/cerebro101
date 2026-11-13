"use client";
import { useCallback, useEffect, useState } from "react";
import { cantidadAEnvio, eurosTexto, faltaEnPartidasTexto } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

/** Partidas de equipos y su coste real: los productos de la tabla de equivalencias, con la cantidad que pone una persona y el coste calculado con las tarifas de proveedor (cambio y logística incluidos).
 *  CONFIDENCIAL: solo lo ve Licitaciones y Dirección, y solo lo usa el modelo local de Costes y de Precio; nunca sale a Claude ni a ChatGPT. */
export default function Partidas({ id, version }) {
  const [d, setD] = useState(undefined);
  const [abierto, setAbierto] = useState(false);
  const [error, setError] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const [nuevo, setNuevo] = useState("");
  const [cantNueva, setCantNueva] = useState("");
  const cargar = useCallback(async () => {
    try { setD(await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/partidas`)); }
    catch { setD((x) => (x === undefined ? null : x)); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar, version]);
  if (d === undefined || d === null) return null;

  const ruta = `licitaciones/ofertas/${encodeURIComponent(id)}/partidas`;
  const hacer = async (f) => {
    setTrabajando(true); setError(null);
    try { setD(await f()); } catch (e) { setError(e); } finally { setTrabajando(false); }
  };
  const t = d.totales;
  return (
    <section className="tarjeta" aria-label="Partidas de equipos y coste">
      <header>
        <h3>Equipos y coste real</h3>
        <button className="boton no" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>{abierto ? "Ocultar" : "Ver"}</button>
      </header>
      <p className="meta">Confidencial: el coste sale de las tarifas de proveedor (con cambio y logística) y solo lo usa el modelo local de Costes y de Precio; no sale a Claude ni a ChatGPT. Es de referencia: el precio lo fijas tú.</p>
      <p><strong>Coste total: {eurosTexto(t.coste_eur)}</strong> · venta de referencia con margen: {eurosTexto(t.venta_referencia_eur)} (sin IVA) · {t.completas} de {t.partidas} partidas completas</p>
      {faltaEnPartidasTexto(t) && <p className="aviso" role="note">{faltaEnPartidasTexto(t)}</p>}
      {d.aviso && <p className="aviso" role="alert">{d.aviso}</p>}
      {error && <p className="aviso" role="alert">{error.detalle || "No se ha podido hacer."}</p>}
      <p className="lic-fila">
        <button className="boton si" disabled={trabajando} onClick={() => hacer(() => pedirCerebro(`${ruta}/proponer`, enviar({})))}>{d.partidas.length ? "Actualizar desde la tabla de equivalencias" : "Calcular desde la tabla de equivalencias"}</button>
      </p>
      {abierto && (
        <>
          <table className="lic-tabla">
            <thead><tr><th>Producto</th><th>Cantidad</th><th>Coste unitario</th><th>Proveedor</th><th>Subtotal</th><th /></tr></thead>
            <tbody>
              {d.partidas.map((p) => (
                <tr key={p.id} style={p.excluida ? { opacity: 0.5 } : undefined}>
                  <td>{p.producto}{p.parametros?.length > 0 && <span className="meta"> · cubre: {p.parametros.join("; ")}</span>}{p.coste_unit_eur === null && <span className="lic-etiqueta aviso">{p.motivo}</span>}</td>
                  <td><input defaultValue={p.cantidad ?? ""} inputMode="decimal" size={6} aria-label={`Cantidad de ${p.producto}`} disabled={trabajando}
                    onBlur={(e) => { const v = cantidadAEnvio(e.target.value); if (v !== (p.cantidad ?? null)) hacer(() => pedirCerebro(`${ruta}/${p.id}`, enviar({ cantidad: v }))); }} /></td>
                  <td>{eurosTexto(p.coste_unit_eur)}{p.avisos?.length > 0 && <span className="meta" title={p.avisos.join(" · ")}> ⚠</span>}</td>
                  <td>{p.proveedor ? `${p.proveedor} (${p.canal})` : "—"}</td>
                  <td>{eurosTexto(p.subtotal_eur)}</td>
                  <td>
                    <button className="boton no" disabled={trabajando} onClick={() => hacer(() => pedirCerebro(`${ruta}/${p.id}`, enviar({ excluida: !p.excluida })))}>{p.excluida ? "Incluir" : "Excluir"}</button>
                    {p.origen === "manual" && <button className="boton no" disabled={trabajando} onClick={() => hacer(() => pedirCerebro(`${ruta}/${p.id}/quitar`, enviar({})))}>Quitar</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="lic-fila">
            <input value={nuevo} onChange={(e) => setNuevo(e.target.value)} placeholder="Añadir producto: marca y referencia" maxLength={160} aria-label="Producto a añadir" />
            <input value={cantNueva} onChange={(e) => setCantNueva(e.target.value)} placeholder="Cantidad" inputMode="decimal" size={6} aria-label="Cantidad del producto a añadir" />
            <button className="boton no" disabled={trabajando || nuevo.trim().length < 2} onClick={() => hacer(async () => { const r = await pedirCerebro(ruta, enviar({ producto: nuevo, cantidad: cantidadAEnvio(cantNueva) })); setNuevo(""); setCantNueva(""); return r; })}>Añadir</button>
          </div>
        </>
      )}
    </section>
  );
}
