"use client";
import { useCallback, useEffect, useState } from "react";
import { pedirCerebro } from "../licitaciones/cliente";
import { fuenteTexto, mensajeMarcas, resumenMarca, resumenProveedor, variantesTexto } from "../../lib/proveedoresMarcas";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

/** Qué marcas distribuye cada proveedor, deducido de sus tarifas cargadas y guardado; se pueden añadir a mano las que no vengan en la tarifa. Sirve para saber a quién pedir precio o cotización de una marca. */
export default function ProveedoresMarcas() {
  const [d, setD] = useState(undefined);        // undefined = cargando; null = sin acceso
  const [busca, setBusca] = useState("");
  const [msg, setMsg] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const [nuevo, setNuevo] = useState({ proveedor: "", marca: "" });

  const cargar = useCallback(async (marca = "") => {
    try { setD(await pedirCerebro(`precios/proveedores-marcas${marca ? `?marca=${encodeURIComponent(marca)}` : ""}`)); setMsg(null); }
    catch (e) { if (e.status === 403) setD(null); else { setMsg({ mal: true, texto: mensajeMarcas(e.status, e.detalle) }); setD((x) => (x === undefined ? null : x)); } }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);

  const hacer = async (f, ok) => {
    setOcupado(true); setMsg(null);
    try { const r = await f(); setMsg({ mal: false, texto: ok(r) }); await cargar(busca.trim()); }
    catch (e) { setMsg({ mal: true, texto: mensajeMarcas(e.status, e.detalle) }); } finally { setOcupado(false); }
  };
  const reconstruir = () => hacer(() => pedirCerebro("precios/proveedores-marcas/reconstruir", enviar({})), (r) => `Recalculado desde las tarifas cargadas: ${r.proveedores} proveedores.`);
  const anadir = () => hacer(() => pedirCerebro("precios/proveedores-marcas/manual", enviar({ ...nuevo, accion: "anadir" })), (r) => `Añadida ${r.marca} a ${r.proveedor}.`).then(() => setNuevo((n) => ({ ...n, marca: "" })));
  const quitar = (proveedor, marca) => hacer(() => pedirCerebro("precios/proveedores-marcas/manual", enviar({ proveedor, marca, accion: "quitar" })), () => `Quitada ${marca} de ${proveedor}.`);

  if (d === undefined || d === null) return d === null && msg ? <p role="alert" className="lic-error">{msg.texto}</p> : null;
  return (
    <section className="tarjeta" aria-label="Proveedores y marcas">
      <h2>Proveedores y marcas</h2>
      <p className="meta">Qué marcas distribuye cada proveedor, deducido de sus tarifas cargadas (sin precios) y guardado. Las variantes que traen las tarifas («HIKVISION PRO NO CCTV»…) se juntan bajo el fabricante; se editan en <code>config/marcas_alias.yaml</code>.</p>
      <form className="lic-fila" onSubmit={(e) => { e.preventDefault(); cargar(busca.trim()); }}>
        <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="¿Quién distribuye…? (Hikvision, Ajax…)" aria-label="Buscar una marca" maxLength={60} />
        <button className="boton si" type="submit" disabled={ocupado}>Buscar</button>
        {d.marca && <button className="boton no" type="button" onClick={() => { setBusca(""); cargar(""); }}>Ver todos</button>}
        <button className="boton no" type="button" disabled={ocupado} onClick={reconstruir} title="Vuelve a deducir las marcas de todas las tarifas ya cargadas (lo puesto a mano no se toca)">Recalcular desde las tarifas</button>
      </form>
      {msg && <p role={msg.mal ? "alert" : "status"} className={msg.mal ? "lic-error" : "aviso"}>{msg.texto}</p>}
      {d.proveedores.length === 0 && <p className="meta">{d.marca ? `Ningún proveedor distribuye «${d.marca}» según lo guardado.` : "Aún no hay marcas guardadas: carga una tarifa, o pulsa «Recalcular desde las tarifas» si ya tienes tarifas cargadas."}</p>}
      {d.proveedores.map((p) => (
        <details key={p.proveedor} open={!!d.marca}>
          <summary><strong>{resumenProveedor(p)}</strong></summary>
          <ul>
            {p.marcas.map((m) => (
              <li key={m.clave}>{resumenMarca(m)}
                {variantesTexto(m.variantes) && <div className="meta">Como la escribe la tarifa: {variantesTexto(m.variantes)}</div>}
                {m.fuentes.includes("manual") && <button className="boton no" disabled={ocupado} onClick={() => quitar(p.proveedor, m.marca)} title={`Quita la marca puesta a mano (${fuenteTexto(m.fuentes)})`}>Quitar la de a mano</button>}
              </li>
            ))}
          </ul>
        </details>
      ))}
      <h3>Añadir a mano</h3>
      <p className="meta">Una marca que un proveedor distribuye aunque no venga en su tarifa (por ejemplo, un distribuidor autorizado al que se le pide cotización).</p>
      <div className="lic-fila">
        <input value={nuevo.proveedor} onChange={(e) => setNuevo((n) => ({ ...n, proveedor: e.target.value }))} placeholder="Proveedor (como en la tarifa)" aria-label="Proveedor" maxLength={80} />
        <input value={nuevo.marca} onChange={(e) => setNuevo((n) => ({ ...n, marca: e.target.value }))} placeholder="Marca" aria-label="Marca" maxLength={60} />
        <button className="boton no" disabled={ocupado || nuevo.proveedor.trim().length < 2 || !nuevo.marca.trim()} onClick={anadir}>Añadir</button>
      </div>
    </section>
  );
}
