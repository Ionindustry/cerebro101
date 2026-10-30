"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { agruparPorAnexo, clasePaso, clasePlantilla, empresaParaEnviar, mensajeRedaccion, origenTexto, pasoEtiqueta, pendientesQueBloquean, plantillaEtiqueta, redaccionEnCurso, resumenPlantillas, resumenRedaccion } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
const SONDEO_MS = 4000;

/** «Preparar la oferta» con los agentes: elige la sociedad del ERP con la que se presenta, lanza a los agentes (Arquitecto, Redactor, Administrativo, Costes, Precio, Evaluador), enseña su progreso
 *  y la documentación administrativa rellenada (las plantillas del concurso, en copias, listas para revisar y firmar con certificado digital). Los agentes solo escriben borradores. */
export default function Redaccion({ id, o, alCambiar }) {
  const [empresas, setEmpresas] = useState(null);
  const [errorEmpresas, setErrorEmpresas] = useState("");
  const [elegida, setElegida] = useState("");
  const [rehacer, setRehacer] = useState(false);
  const [ejec, setEjec] = useState(null);
  const [plant, setPlant] = useState(null);
  const [msg, setMsg] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const vivo = useRef(true);
  useEffect(() => { vivo.current = true; return () => { vivo.current = false; }; }, []);

  const cargarPlantillas = useCallback(async () => {
    try { const r = await pedirCerebro(`licitaciones/ofertas/${id}/plantillas`); if (vivo.current) setPlant(r); } catch { /* sin oferta aún o sin permiso: la tarjeta no lo enseña */ }
  }, [id]);
  const cargarEjecucion = useCallback(async () => {
    try { const r = await pedirCerebro(`licitaciones/ofertas/${id}/ejecucion`); if (vivo.current) setEjec(r.ejecucion); return r.ejecucion; } catch { return null; }
  }, [id]);

  useEffect(() => {
    cargarEjecucion(); cargarPlantillas();
    pedirCerebro("licitaciones/empresas").then((r) => { if (vivo.current) setEmpresas(r.empresas); })
      .catch((e) => { if (vivo.current) { setEmpresas([]); setErrorEmpresas(mensajeRedaccion(e.status, e.detalle)); } });
  }, [id]);                                                                  // eslint-disable-line react-hooks/exhaustive-deps

  // Al fijar el precio, los modelos de proposición económica ya preparados se rellenan con el importe: se vuelven a leer.
  useEffect(() => { if (o?.precio_en) cargarPlantillas(); }, [o?.precio_en]);        // eslint-disable-line react-hooks/exhaustive-deps

  // Mientras los agentes trabajan se pregunta cada pocos segundos; al terminar se recarga la oferta (las secciones ya escritas) y las plantillas.
  const trabajandoAgentes = redaccionEnCurso(ejec);
  useEffect(() => {
    if (!trabajandoAgentes) return undefined;
    const t = setInterval(async () => {
      const e = await cargarEjecucion();
      if (e && !redaccionEnCurso(e)) { await alCambiar(); await cargarPlantillas(); }
    }, SONDEO_MS);
    return () => clearInterval(t);
  }, [trabajandoAgentes]);                                                   // eslint-disable-line react-hooks/exhaustive-deps

  const sociedad = empresaParaEnviar(elegida, o?.empresa);
  const lista = empresas || [];
  const hayVarias = lista.length > 1;
  const redactar = async () => {
    setTrabajando(true); setMsg(null);
    try {
      const r = await pedirCerebro(`licitaciones/ofertas/${id}/redactar`, enviar({ rehacer, ...(sociedad ? { empresa: sociedad } : {}) }));
      setEjec(r.ejecucion);
      await alCambiar();
    } catch (e) {
      if (e.status === 409 && e.empresas) { setEmpresas(e.empresas); setMsg("Hay varias sociedades en el ERP: elige con cuál se presenta esta oferta y vuelve a pulsar."); }
      else setMsg(mensajeRedaccion(e.status, e.detalle));
    } finally { setTrabajando(false); }
  };
  const rellenar = async () => {
    setTrabajando(true); setMsg(null);
    try { setPlant(await pedirCerebro(`licitaciones/ofertas/${id}/plantillas`, enviar(sociedad ? { empresa: sociedad } : {}))); await alCambiar(); }
    catch (e) {
      if (e.status === 409 && e.empresas) { setEmpresas(e.empresas); setMsg("Hay varias sociedades en el ERP: elige con cuál se presenta esta oferta y vuelve a pulsar."); }
      else setMsg(mensajeRedaccion(e.status, e.detalle));
    } finally { setTrabajando(false); }
  };
  const descargar = async (d) => {
    setMsg(null);
    try {
      const f = await pedirCerebro(`licitaciones/ofertas/${id}/plantillas/${d.id}/fichero`);
      const bytes = Uint8Array.from(atob(f.base64), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: f.tipo }));
      const a = document.createElement("a"); a.href = url; a.download = f.nombre; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setMsg(mensajeRedaccion(e.status, e.detalle)); }
  };

  return (
    <div className="lic-redaccion">
      <h3>Preparar la oferta con los agentes</h3>
      <p className="meta">Los agentes trabajan uno detrás de otro (Arquitecto de Solución, Redactor de Memoria, Administrativo, Costes, Precio y Evaluador) a partir del pliego. Solo dejan <strong>borradores</strong>: tú los revisas, fijas el precio y firmas. Puede tardar varios minutos.</p>
      <div className="lic-fila">
        {hayVarias && (
          <label>Sociedad con la que se presenta
            <select value={elegida || o?.empresa || ""} onChange={(e) => setElegida(e.target.value)} aria-label="Sociedad con la que se presenta la oferta">
              <option value="">Elige una…</option>
              {lista.map((x) => <option key={x.nombre} value={x.nombre}>{x.razon_social}{x.nif ? ` (${x.nif})` : ""}</option>)}
            </select>
          </label>
        )}
        {!hayVarias && lista.length === 1 && <span className="meta">Sociedad: <strong>{lista[0].razon_social}</strong> ({lista[0].nif || "sin NIF en el ERP"})</span>}
        <button className="boton si" onClick={redactar} disabled={trabajando || trabajandoAgentes || (hayVarias && !sociedad)}>
          {trabajandoAgentes ? "Los agentes están trabajando…" : o?.existe ? "Redactar con los agentes lo que falte" : "Preparar la oferta con los agentes"}
        </button>
        {o?.existe && <label className="ap-check"><input type="checkbox" checked={rehacer} onChange={(e) => setRehacer(e.target.checked)} /> Rehacer también los borradores de los agentes</label>}
      </div>
      {errorEmpresas && <p className="meta" role="note">No se han podido leer las sociedades del ERP: {errorEmpresas}</p>}

      {ejec && (
        <div aria-live="polite">
          <p><strong>{resumenRedaccion(ejec)}</strong></p>
          <ol className="lic-pasos">
            {ejec.pasos.map((p) => (
              <li key={p.id}>
                <span className="lic-fila"><span className={`lic-etiqueta ${clasePaso(p.estado)}`}>{pasoEtiqueta(p.estado)}</span><strong>{p.titulo}</strong></span>
                {p.error && <span className="meta lic-aviso">{p.error}</span>}
                {p.faltan?.length > 0 && <span className="meta">Sin escribir: {p.faltan.join(", ")}</span>}
                {p.resumen && <details><summary className="meta">Qué ha hecho{p.id === "precio" ? " (precio orientativo: lo fija una persona)" : ""}</summary><p style={{ whiteSpace: "pre-line" }}>{p.resumen}</p></details>}
              </li>
            ))}
          </ol>
          {ejec.error && <p role="alert" className="lic-error">{ejec.error}</p>}
        </div>
      )}

      <h3>Documentación administrativa {plant?.documentos?.length > 0 && <span className="meta">· {resumenPlantillas(plant)}</span>}</h3>
      <p className="meta">Las plantillas del concurso (declaración responsable, anexos…) se rellenan en una <strong>copia</strong> con los datos de la sociedad elegida, que salen del ERP; el documento original no se toca.
        Lo que falte se completa en el ERP (si es un dato de la empresa) o a mano en el documento.
        Los <strong>modelos de proposición económica</strong> se rellenan con el precio cuando una persona lo fija (importe en número y en letra, IVA y total); el precio nunca lo escribe un agente.</p>
      <div className="lic-fila"><button className="boton no" onClick={rellenar} disabled={trabajando || trabajandoAgentes || (hayVarias && !sociedad) || !o?.existe} title={o?.existe ? "Rellena de nuevo desde el original todas las plantillas del concurso" : "Primero hay que preparar la oferta"}>Rellenar las plantillas del concurso</button></div>
      {plant?.documentos?.length === 0 && <p className="meta">Todavía no hay plantillas rellenadas. Primero baja y lee los documentos del pliego (tarjeta «Pliegos»): se buscan las plantillas en Word y en PDF con formulario.</p>}
      {(plant?.documentos || []).map((d) => {
        const bloquean = pendientesQueBloquean(d);
        return (
          <details key={d.id} className="lic-informe" open={d.estado !== "lista_para_firma" || undefined}>
            <summary><strong>{d.nombre}</strong> <span className={`lic-etiqueta ${clasePlantilla(d.estado)}`}>{plantillaEtiqueta(d.estado)}</span></summary>
            <p className="meta">{d.documento === 0 ? "DEUC de la sociedad (los campos propios del concurso)" : `Documento ${d.documento} del pliego`}{d.empresa ? ` · rellenado con los datos de ${d.empresa}` : ""} · {d.rellenados.length} {d.rellenados.length === 1 ? "hueco rellenado" : "huecos rellenados"}</p>
            {d.avisos.map((a, i) => <p key={i} className="meta lic-aviso">{a}</p>)}
            {agruparPorAnexo(d).map((g) => (
              <div key={g.anexo || "_"}>
                {(g.anexo || agruparPorAnexo(d).length > 1) && <p><strong>{g.anexo || "Resto del documento"}</strong> <span className="meta">· {g.rellenados.length} rellenados{g.pendientes.length > 0 ? ` · ${g.pendientes.filter((p) => p.bloquea).length} por completar` : ""}</span></p>}
                {g.rellenados.length > 0 && (
                  <ul className="lic-historial">{g.rellenados.slice(0, 40).map((r) => <li key={r.id}><span className="meta">{r.etiqueta || r.tipo}</span> → {r.valor} <span className="meta">({origenTexto(r.origen)})</span></li>)}</ul>
                )}
                {g.pendientes.length > 0 && (
                  <>
                    <p className="meta">{g.pendientes.some((p) => p.bloquea) ? "Falta antes de firmar:" : "Se completa al firmar:"}</p>
                    <ul className="lic-historial">{g.pendientes.map((p) => <li key={p.id}><span className="meta">{p.etiqueta || p.tipo}</span> — {p.motivo}{p.bloquea ? "" : " (no impide firmar)"}</li>)}</ul>
                  </>
                )}
              </div>
            ))}
            {d.fichero && <div className="lic-fila"><button className="boton si" onClick={() => descargar(d)}>Descargar {d.formato.toUpperCase()} rellenado</button></div>}
          </details>
        );
      })}
      {plant?.documentos?.length > 0 && <p className="meta">{plant.nota}</p>}
      {msg && <p role="alert" className="lic-error">{msg}</p>}
    </div>
  );
}
