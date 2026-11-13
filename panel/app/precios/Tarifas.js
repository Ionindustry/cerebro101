"use client";
import { useCallback, useEffect, useState } from "react";
import { ESTADO_TARIFA, cambiosTarifaTexto, haceTexto } from "../../lib/precios";
import { pedirCerebro } from "../licitaciones/cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

/** Tarifas de proveedores: se vigilan carpetas y servicios web; cada fichero nuevo deja una propuesta con sus cambios frente a la última cargada. Nada se carga en el ERP sin la firma de Dirección. */
export default function Tarifas({ alCargarTarifa }) {
  const [d, setD] = useState(undefined);
  const [vista, setVista] = useState(null);             // {actualizacion, cambios, vista}
  const [confirmo, setConfirmo] = useState(false);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const cargar = useCallback(async () => {
    try { setD(await pedirCerebro("precios/tarifas")); } catch { setD((x) => (x === undefined ? null : x)); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  if (d === undefined || d === null) return null;

  const hacer = async (fn, ok) => {
    setTrabajando(true); setError(null); setAviso(null);
    try { const r = await fn(); if (ok) setAviso(ok(r)); await cargar(); return r; } catch (e) { setError(e); } finally { setTrabajando(false); }
  };
  const pendientes = d.actualizaciones.filter((a) => a.estado === "pendiente");
  const recientes = d.actualizaciones.filter((a) => a.estado !== "pendiente").slice(0, 5);
  return (
    <section className="tarjeta" aria-label="Tarifas de proveedores">
      <h2>Tarifas de proveedores</h2>
      <p className="meta">Cada día se mira lo que hay en las carpetas y servicios web de tus proveedores. Un fichero nuevo deja aquí una propuesta con sus cambios; <strong>no se carga nada en el ERP hasta que lo firmes</strong>, y cargar costes no cambia ningún precio de venta.</p>
      {error && <p className="aviso" role="alert">{error.detalle || "No se ha podido hacer."}</p>}
      {aviso && <p className="aviso" role="status">{aviso}</p>}
      {d.errores_configuracion.length > 0 && <ul className="aviso">{d.errores_configuracion.map((e, i) => <li key={i}>Configuración: {e}</li>)}</ul>}
      {d.proveedores.length === 0
        ? <p className="meta">No hay proveedores configurados. Añádelos en <code>config/tarifas_auto.yaml</code> (carpeta o servicio web) y se vigilarán solos.</p>
        : <ul className="lic-lista">{d.proveedores.map((p) => (
          <li key={p.id} className="lic-fila">
            <strong>{p.nombre}</strong><span className="lic-etiqueta">{p.origen === "carpeta" ? "carpeta" : "servicio web"} · {p.canal}</span>
            <span className="meta">comprobado {haceTexto(p.ultimo_intento)}</span>
            {p.error && <span className="lic-etiqueta aviso" title={p.error}>falló: {p.error.slice(0, 80)}</span>}
          </li>))}</ul>}
      <p className="lic-fila">
        <button className="boton no" disabled={trabajando || d.proveedores.length === 0} onClick={() => hacer(() => pedirCerebro("precios/tarifas/comprobar", enviar({})), () => "Comprobación lanzada: en un minuto, pulsa «Actualizar» para ver lo que haya.")}>Comprobar ahora</button>
        <button className="boton no" disabled={trabajando} onClick={() => cargar()}>Actualizar</button>
      </p>

      {pendientes.map((a) => (
        <div key={a.id} className="tarjeta lic-item">
          <span className="lic-fila"><strong>{a.proveedor_id}</strong><span className="meta">{a.nombre}</span><span className="lic-etiqueta aviso">{ESTADO_TARIFA[a.estado]}</span></span>
          <span>{cambiosTarifaTexto(a.cambios)}</span>
          {a.cambios?.avisos?.map((x, i) => <span key={i} className="aviso" role="alert">⚠ {x}</span>)}
          {a.cambios?.mayores?.length > 0 && <span className="meta">Mayores cambios: {a.cambios.mayores.slice(0, 5).map((m) => `${m.codigo} ${m.variacion_pct} %`).join(" · ")}</span>}
          <span className="lic-fila">
            <button className="boton no" disabled={trabajando} onClick={() => { setConfirmo(false); hacer(async () => setVista(await pedirCerebro(`precios/tarifas/${a.id}`))); }}>Ver lo que se cargaría</button>
            <button className="boton no" disabled={trabajando} onClick={() => window.confirm("¿Descartar esta tarifa? No se cargará nada en el ERP.") && hacer(async () => { await pedirCerebro(`precios/tarifas/${a.id}/descartar`, enviar({})); setVista(null); })}>Descartar</button>
          </span>
          {vista?.actualizacion === a.id && (
            <div className="lic-aviso" role="group" aria-label="Vista previa de la tarifa">
              <dl className="lic-ficha">{vista.vista.vista.campos.map(([k, v]) => <div key={k}><dt>{k}</dt><dd style={{ whiteSpace: "pre-line" }}>{v}</dd></div>)}</dl>
              <label className="ap-check"><input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} /> He revisado la vista previa y firmo que se cargue esta tarifa en el ERP (proveedor, artículos y costes).</label>
              <button className="boton si" disabled={trabajando || !confirmo} onClick={() => window.confirm("Vas a cargar esta tarifa en el ERP. Queda registrado a tu nombre. ¿Seguir?") && hacer(async () => { const r = await pedirCerebro(`precios/tarifas/${a.id}/aplicar`, enviar({ confirmo: true })); setVista(null); setConfirmo(false); if (alCargarTarifa) alCargarTarifa(); return r; }, () => "Tarifa cargada. Ahora puedes calcular una propuesta de precios de venta con los costes nuevos.")}>Cargar la tarifa en el ERP</button>
            </div>
          )}
        </div>
      ))}
      {pendientes.length === 0 && d.proveedores.length > 0 && <p className="meta">No hay tarifas nuevas pendientes.</p>}
      {recientes.length > 0 && <details><summary className="meta">Últimas decididas ({recientes.length})</summary><ul>{recientes.map((a) => <li key={a.id} className="meta">{a.proveedor_id} · {a.nombre} · {ESTADO_TARIFA[a.estado]}{a.motivo ? ` — ${a.motivo}` : ""}{a.decidido_por ? ` · ${a.decidido_por}` : ""}</li>)}</ul></details>}
    </section>
  );
}
