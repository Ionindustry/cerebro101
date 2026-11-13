"use client";
import { useCallback, useEffect, useState } from "react";
import { CAMBIO_ETIQUETA, ESTADO_PROPUESTA, MENSAJE_APLICAR, consultaLineas, euros, margenTexto, precioAEnvio, resumenPropuestaTexto } from "../../lib/precios";
import { fechaTexto } from "../../lib/licitaciones";
import { pedirCerebro } from "../licitaciones/cliente";
import Tarifas from "./Tarifas";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
const CLASE_CAMBIO = { nuevo: "ok", sube: "aviso", baja: "aviso", igual: "" };

/** Revisión y aprobación de los precios de venta (solo Dirección). Las propuestas las calcula el código a partir de los costes cargados, el margen de cada familia y el cambio del día; aquí se revisan,
 *  se ajustan a mano o por estrategia (competitivo, alineado, premium) y, cuando Dirección firma, se escriben en el ERP. Nada llega al ERP sin la confirmación expresa. */
export default function Precios() {
  const [lista, setLista] = useState(undefined);       // undefined = cargando; null = sin acceso
  const [sel, setSel] = useState(null);                 // id de la propuesta abierta
  const [d, setD] = useState(null);
  const [f, setF] = useState({ familia: "", cambio: "", texto: "", bajoMinimo: false });
  const [pagina, setPagina] = useState(1);
  const [marca, setMarca] = useState("");
  const [estrategia, setEstrategia] = useState("");
  const [confirmo, setConfirmo] = useState(false);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [trabajando, setTrabajando] = useState(false);

  const cargarLista = useCallback(async () => {
    try { setLista((await pedirCerebro("precios/propuestas")).propuestas); }
    catch (e) { setLista(null); if (e.status !== 403) setError(e); }
  }, []);
  useEffect(() => { cargarLista(); }, [cargarLista]);

  const cargar = useCallback(async () => {
    if (!sel) { setD(null); return; }
    try { setD(await pedirCerebro(`precios/propuestas/${sel}${consultaLineas(f, pagina)}`)); setError(null); }
    catch (e) { setError(e); }
  }, [sel, f, pagina]);
  useEffect(() => { cargar(); }, [cargar]);

  const hacer = async (fn, ok) => {
    setTrabajando(true); setError(null); setAviso(null);
    try { const r = await fn(); if (ok) setAviso(ok(r)); await cargar(); await cargarLista(); return r; }
    catch (e) { setError(e); } finally { setTrabajando(false); }
  };
  const ruta = `precios/propuestas/${sel}`;
  const proponer = () => hacer(async () => { const r = await pedirCerebro("precios/propuestas", enviar(marca ? { solo_marca: marca } : {})); setSel(r.propuesta); setPagina(1); return r; }, () => "Propuesta calculada: aún no se ha escrito nada en el ERP.");
  const ajustarPrecio = (l, texto) => {
    const v = precioAEnvio(texto);
    if (v === null) { setError({ detalle: "Escribe un precio válido (por ejemplo 199,50)." }); return; }
    if (String(Number(l.venta)) === String(v)) return;
    hacer(() => pedirCerebro(`${ruta}/ajustar`, enviar({ ajustes: { [l.codigo]: v } })));
  };
  const aplicar = () => {
    if (!confirmo || !window.confirm(MENSAJE_APLICAR)) return;
    hacer(() => pedirCerebro(`${ruta}/aplicar`, enviar({ confirmo: true })), (r) => `Aplicado: ${r.resultado.precios_nuevos} precios nuevos y ${r.resultado.precios_actualizados} actualizados${r.resultado.errores?.length ? `; ${r.resultado.errores.length} con error` : ""}.`).then(() => setConfirmo(false));
  };

  if (lista === undefined) return <main><p>Cargando…</p></main>;
  if (lista === null) return <main className="lic"><h1>Precios</h1>{error ? <p className="aviso" role="alert">{error.detalle || "No se ha podido cargar."}</p> : <p>Los precios de venta los revisa y aprueba Dirección.</p>}</main>;

  return (
    <main className="lic">
      <h1>Precios de venta</h1>
      <p className="meta">Confidencial (lleva costes de proveedor). El precio sale de: mejor coste ya en euros (cambio y logística) ÷ (1 − margen de la familia), redondeado. Los costes o el cambio que cambian <strong>no tocan ningún precio solos</strong>: solo cambia lo que tú apruebas.</p>
      {error && <p className="aviso" role="alert">{error.detalle || "No se ha podido hacer."}</p>}
      {aviso && <p className="aviso" role="status">{aviso}</p>}

      <Tarifas alCargarTarifa={cargarLista} />

      <section className="tarjeta">
        <h2>Propuestas de precios de venta</h2>
        <p className="lic-fila">
          <input value={marca} onChange={(e) => setMarca(e.target.value)} placeholder="Solo una marca (opcional)" maxLength={60} aria-label="Marca" />
          <button className="boton si" disabled={trabajando} onClick={proponer}>Calcular una propuesta nueva</button>
        </p>
        <ul className="lic-lista">
          {lista.map((p) => (
            <li key={p.id} className="tarjeta lic-item">
              <button className="boton no" onClick={() => { setSel(p.id); setPagina(1); setConfirmo(false); }} aria-pressed={sel === p.id}>Propuesta {p.id}</button>
              <span className={`lic-etiqueta ${p.estado === "aplicada" ? "ok" : p.estado === "propuesta" ? "aviso" : ""}`}>{ESTADO_PROPUESTA[p.estado] || p.estado}</span>
              <span className="meta">{fechaTexto(p.creado)} · {resumenPropuestaTexto(p.resumen)}</span>
            </li>
          ))}
          {lista.length === 0 && <li className="meta">Aún no hay propuestas. Hace falta haber cargado y aprobado la tarifa de algún proveedor.</li>}
        </ul>
      </section>

      {d && (
        <section className="tarjeta" aria-label={`Propuesta ${d.propuesta}`}>
          <h2>Propuesta {d.propuesta} · lista «{d.lista}»</h2>
          <p><span className="lic-etiqueta">{ESTADO_PROPUESTA[d.estado] || d.estado}</span> {resumenPropuestaTexto(d.resumen)}</p>
          {d.avisos?.length > 0 && <ul className="aviso">{d.avisos.map((a, i) => <li key={i}>{a}</li>)}</ul>}
          {d.resumen?.provisional?.length > 0 && <ul className="aviso">{d.resumen.provisional.slice(0, 5).map((a, i) => <li key={i}>{a}</li>)}</ul>}

          {d.editable && d.estrategias.length > 0 && (
            <p className="lic-fila">
              <label>Estrategia{" "}
                <select value={estrategia} onChange={(e) => setEstrategia(e.target.value)} aria-label="Estrategia de precio">
                  <option value="">Elige…</option>
                  {d.estrategias.map((x) => <option key={x} value={x}>{x}</option>)}
                </select>
              </label>
              <button className="boton no" disabled={trabajando || !estrategia} onClick={() => hacer(() => pedirCerebro(`${ruta}/estrategia`, enviar({ estrategia, ...(f.familia ? { familia: f.familia } : {}) })), (r) => `Estrategia «${estrategia}» aplicada a ${r.articulos} artículos.`)}>
                Aplicar a {f.familia ? `la familia ${f.familia}` : "todos los artículos"}
              </button>
              <span className="meta">Solo a los que tienen precios de la competencia anotados. Nunca baja del margen mínimo ({margenTexto(d.margen_minimo)}).</span>
            </p>
          )}

          <div className="lic-fila">
            <select value={f.familia} onChange={(e) => { setF({ ...f, familia: e.target.value }); setPagina(1); }} aria-label="Familia">
              <option value="">Todas las familias</option>{d.familias.map((x) => <option key={x} value={x}>{x || "(sin familia)"}</option>)}
            </select>
            <select value={f.cambio} onChange={(e) => { setF({ ...f, cambio: e.target.value }); setPagina(1); }} aria-label="Tipo de cambio">
              <option value="">Todos los cambios</option>{Object.entries(CAMBIO_ETIQUETA).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
            </select>
            <input value={f.texto} onChange={(e) => { setF({ ...f, texto: e.target.value }); setPagina(1); }} placeholder="Buscar código, referencia o descripción" aria-label="Buscar" maxLength={80} />
            <label className="ap-check"><input type="checkbox" checked={f.bajoMinimo} onChange={(e) => { setF({ ...f, bajoMinimo: e.target.checked }); setPagina(1); }} /> Solo bajo el margen mínimo</label>
          </div>

          <table className="lic-tabla">
            <thead><tr><th>Artículo</th><th>Coste</th><th>Precio de venta</th><th>Margen</th><th>Ahora en el ERP</th><th>Competencia / estrategias</th><th /></tr></thead>
            <tbody>
              {d.lineas.map((l) => (
                <tr key={l.codigo} style={l.excluida ? { opacity: 0.5 } : undefined}>
                  <td><strong>{l.ref}</strong> <span className="meta">{l.marca} · {l.familia}</span><br /><span className="meta">{l.desc}</span>{l.avisos?.length > 0 && <span className="meta" title={l.avisos.join(" · ")}> ⚠</span>}</td>
                  <td>{euros(l.coste_eur)}<br /><span className="meta">{l.proveedor}</span></td>
                  <td>{d.editable
                    ? <input key={`${l.codigo}-${l.venta}`} defaultValue={String(l.venta).replace(".", ",")} size={8} inputMode="decimal" disabled={trabajando} aria-label={`Precio de venta de ${l.ref}`} onBlur={(e) => ajustarPrecio(l, e.target.value)} />
                    : euros(l.venta)}{l.ajustado && <span className="lic-etiqueta">a mano</span>}</td>
                  <td>{margenTexto(l.margen)}</td>
                  <td>{euros(l.actual)} <span className={`lic-etiqueta ${CLASE_CAMBIO[l.cambio] || ""}`}>{CAMBIO_ETIQUETA[l.cambio] || l.cambio}{l.variacion_pct ? ` ${l.variacion_pct} %` : ""}</span></td>
                  <td className="meta">{l.mercado?.n ? <>mín {euros(l.mercado.minimo)} · mediana {euros(l.mercado.mediana)} · máx {euros(l.mercado.maximo)}<br /></> : null}{Object.entries(l.estrategias || {}).map(([k, v]) => `${k}: ${euros(v)}`).join(" · ") || "sin precios de competencia"}</td>
                  <td>{d.editable && <button className="boton no" disabled={trabajando} onClick={() => hacer(() => pedirCerebro(`${ruta}/ajustar`, enviar(l.excluida ? { incluir: [l.codigo] } : { excluir: [l.codigo] })))}>{l.excluida ? "Incluir" : "Excluir"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="lic-fila">
            <button className="boton no" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>← Anterior</button>
            <span className="meta">Página {d.pagina} · {d.total} artículos</span>
            <button className="boton no" disabled={d.pagina * d.por_pagina >= d.total} onClick={() => setPagina(pagina + 1)}>Siguiente →</button>
          </p>

          {d.estado === "aplicada" && <p className="aviso" role="status">Aplicada en el ERP el {fechaTexto(d.resultado?.fecha || d.creado)}: {d.resultado?.precios_nuevos ?? 0} nuevos, {d.resultado?.precios_actualizados ?? 0} actualizados.</p>}
          {d.editable && d.vista && (
            <div className="lic-aviso" role="group" aria-label="Vista previa de la aplicación">
              <h3>Lo que se aplicaría en el ERP</h3>
              <dl className="lic-ficha">{d.vista.campos.map(([k, v]) => <div key={k}><dt>{k}</dt><dd style={{ whiteSpace: "pre-line" }}>{v}</dd></div>)}</dl>
              <label className="ap-check"><input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} /> He revisado la vista previa y firmo que se apliquen estos precios en el ERP.</label>
              <p className="lic-fila">
                <button className="boton si" disabled={trabajando || !confirmo} onClick={aplicar}>Aplicar en el ERP</button>
                <button className="boton no" disabled={trabajando} onClick={() => window.confirm("¿Descartar esta propuesta? No se escribirá nada en el ERP.") && hacer(() => pedirCerebro(`${ruta}/descartar`, enviar({})))}>Descartar la propuesta</button>
              </p>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
