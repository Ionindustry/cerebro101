"use client";
import { useCallback, useEffect, useState } from "react";
import { pedirCerebro } from "../licitaciones/cliente";
import {
  AMBITO_ETIQUETA, CATEGORIAS_RADAR, COBERTURA_ETIQUETA, datoAnalisisTexto, ESTADO_DOCUMENTO_ETIQUETA, ESTADO_REQUISITO_ETIQUETA, TIPO_REQUISITO_ETIQUETA, agruparRequisitos, lecturaEnMarcha, lecturaTexto, ESTADO_CLASE, ESTADO_ETIQUETA, ESTADO_FUENTE, FILTROS_VACIOS, GRUPOS_ESTADO, INSTRUMENTO_ETIQUETA, grupoActivo, activableMotivo, ejecucionTexto, fechaCorta, filtrosAQuery,
  importeTexto, mensajeError, novedadEtiqueta, plazoTexto, urlSegura,
} from "../../lib/subvenciones";
import { haceTexto } from "../../lib/precios";

const enviar = (metodo, cuerpo) => ({ method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
const PESTANAS = [["radar", "Radar"], ["buscar", "Buscador"], ["mias", "Mis oportunidades"], ["fuentes", "Conectores"]];

function Fila({ o, onAbrir, novedad }) {
  return (
    <li className="tarjeta lic-item">
      <button className="boton no" onClick={() => onAbrir(o.id)} style={{ textAlign: "left" }}>
        <strong>{o.title}</strong>
      </button>
      <span className="lic-fila">
        <span className={`lic-etiqueta ${ESTADO_CLASE[o.status] || ""}`}>{ESTADO_ETIQUETA[o.status] || o.status}</span>
        {(novedad || o.novedad) && <span className="lic-etiqueta ok">{novedadEtiqueta(novedad || o.novedad)}</span>}
        {o.funding_type && <span className="lic-etiqueta">{INSTRUMENTO_ETIQUETA[o.funding_type] || o.funding_type}</span>}
        {o.geographic_scope && <span className="lic-etiqueta">{AMBITO_ETIQUETA[o.geographic_scope] || o.geographic_scope}</span>}
      </span>
      <span className="meta">{o.issuing_organization || "Organismo no indicado"} · presupuesto {importeTexto(o.total_budget, o.currency)} · plazo {fechaCorta(o.deadline)} ({plazoTexto(o.deadline)})</span>
    </li>
  );
}

function Analisis({ id }) {
  const [a, setA] = useState(undefined);
  const [error, setError] = useState(null);
  useEffect(() => { pedirCerebro(`subvenciones/oportunidades/${id}/analisis`).then(setA).catch((e) => { setError(e); setA(null); }); }, [id]);
  if (a === undefined) return <p className="meta">Preparando el análisis…</p>;
  if (!a) return <p className="aviso" role="alert">{mensajeError(error)}</p>;
  const bloque = (titulo, filas) => (
    <div>
      <h4>{titulo}</h4>
      <dl className="lic-ficha">{filas.map(([k, d]) => <div key={k}><dt>{k}</dt><dd style={{ whiteSpace: "pre-line" }} className={d?.consta ? "" : "meta"}>{datoAnalisisTexto(d)}</dd></div>)}</dl>
    </div>
  );
  const t = a.de_que_trata, q = a.a_quien_va_dirigida, b = a.bases_para_presentarse;
  const docs = b.documentos?.valor || [];
  const solicitud = urlSegura(b.como_solicitar?.valor);
  const reguladoras = urlSegura(b.bases_reguladoras?.valor);
  return (
    <section aria-label="Análisis de la convocatoria">
      <h3>Análisis <span className="lic-etiqueta">{COBERTURA_ETIQUETA[a.cobertura] || a.cobertura}</span></h3>
      {a.aviso && <p className="aviso" role="status">{a.aviso}</p>}
      {bloque("De qué trata", [["Resumen", t.descripcion], ["Programa", t.programa], ["Organismo", t.organismo], ["Instrumento", t.instrumento], ["Ámbito", t.ambito]])}
      {bloque("A quién va dirigida", [["Beneficiarios", q.beneficiarios], ["Tamaño de empresa", q.tamanos_de_empresa], ["Sectores", q.sectores]])}
      {bloque("Bases para presentarse", [["Requisitos", b.requisitos], ["Exclusiones", b.exclusiones], ["Gastos subvencionables", b.gastos_subvencionables], ["Importes", b.importes], ["Calendario", b.calendario], ["Estado", { consta: b.estado?.consta, valor: ESTADO_ETIQUETA[b.estado?.valor] || b.estado?.valor }]])}
      <p className="lic-fila">
        {solicitud && <a className="boton no" href={solicitud} target="_blank" rel="noopener noreferrer">Cómo solicitar</a>}
        {reguladoras && <a className="boton no" href={reguladoras} target="_blank" rel="noopener noreferrer">Bases reguladoras</a>}
        {docs.filter((x) => urlSegura(x.url)).map((x, i) => <a key={i} className="boton no" href={urlSegura(x.url)} target="_blank" rel="noopener noreferrer">{x.titulo}</a>)}
      </p>
      <p className="meta">{a.nota}</p>
    </section>
  );
}

function Bases({ id }) {
  const [b, setB] = useState(undefined);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const cargar = useCallback(async () => {
    try { setB(await pedirCerebro(`subvenciones/oportunidades/${id}/bases`)); setError(null); }
    catch (e) { setError(e); setB((x) => x ?? null); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar]);
  const enMarcha = lecturaEnMarcha(b?.lectura);
  useEffect(() => {
    if (!enMarcha) return undefined;
    const t = setInterval(cargar, 5000);
    return () => clearInterval(t);
  }, [enMarcha, cargar]);
  const leer = async () => {
    setError(null); setAviso(null);
    try { await pedirCerebro(`subvenciones/oportunidades/${id}/bases/leer`, enviar("POST")); setAviso("Lectura lanzada: puede tardar unos minutos."); await cargar(); }
    catch (e) { setError(e); }
  };
  const revisar = async (rid, estado) => {
    setError(null);
    try { await pedirCerebro(`subvenciones/requisitos/${rid}`, enviar("PATCH", { estado })); await cargar(); }
    catch (e) { setError(e); }
  };
  if (b === undefined) return <p className="meta">Cargando las bases…</p>;
  const docs = b?.documentos || [];
  return (
    <section aria-label="Lectura de las bases">
      <h3>Bases leídas del documento oficial</h3>
      <p className="meta">{lecturaTexto(b?.lectura)}</p>
      {error && <p className="aviso" role="alert">{mensajeError(error)}</p>}
      {aviso && <p className="aviso" role="status">{aviso}</p>}
      {docs.length > 0
        ? <p className="lic-fila"><button className="boton si" disabled={enMarcha} onClick={leer}>{b?.lectura ? "Volver a leer las bases" : "Leer las bases"}</button></p>
        : <p className="meta">Esta convocatoria no tiene documentos enlazados que leer.</p>}
      {docs.length > 0 && <ul className="lic-lista">{docs.map((d) => (
        <li key={d.id} className="meta">{urlSegura(d.url) ? <a href={urlSegura(d.url)} target="_blank" rel="noopener noreferrer">{d.titulo || "Documento"}</a> : (d.titulo || "Documento")} · {ESTADO_DOCUMENTO_ETIQUETA[d.estado] || d.estado}{d.paginas ? ` · ${d.paginas} págs.` : ""}{d.motivo ? ` · ${d.motivo}` : ""}</li>
      ))}</ul>}
      {agruparRequisitos(b?.requisitos).map(([tipo, lista]) => (
        <div key={tipo}>
          <h4>{TIPO_REQUISITO_ETIQUETA[tipo]}</h4>
          <ul className="lic-lista">{lista.map((r) => (
            <li key={r.id} className="tarjeta lic-item" style={r.estado === "rechazado" ? { opacity: 0.55 } : undefined}>
              <span className="lic-fila"><strong>{r.resumen}</strong><span className={`lic-etiqueta ${r.estado === "confirmado" ? "ok" : ""}`}>{ESTADO_REQUISITO_ETIQUETA[r.estado] || r.estado}</span></span>
              <blockquote style={{ margin: "0.25rem 0", whiteSpace: "pre-line" }}>«{r.cita}»</blockquote>
              <span className="meta">{r.documento || "Documento"} · página {r.pagina}{r.revisado_por ? ` · revisado por ${r.revisado_por}` : ""}</span>
              <span className="lic-fila">
                <button className="boton si" disabled={r.estado === "confirmado"} onClick={() => revisar(r.id, "confirmado")}>Confirmar</button>
                <button className="boton no" disabled={r.estado === "rechazado"} onClick={() => revisar(r.id, "rechazado")}>Rechazar</button>
              </span>
            </li>
          ))}</ul>
        </div>
      ))}
      {b?.requisitos?.length > 0 && <p className="meta">{b.aviso}</p>}
    </section>
  );
}

function Ficha({ id, onCerrar, onCambio }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [nota, setNota] = useState("");
  const [empresa, setEmpresa] = useState("");
  const [proyecto, setProyecto] = useState("");
  const cargar = useCallback(async () => {
    try {
      const r = await pedirCerebro(`subvenciones/oportunidades/${id}`);
      setD(r); setNota(r.guardada?.nota || ""); setEmpresa(r.guardada?.empresa || ""); setProyecto(r.guardada?.proyecto || ""); setError(null);
    } catch (e) { setError(e); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar]);
  const guardar = async (estado) => {
    try { await pedirCerebro(`subvenciones/oportunidades/${id}/guardada`, enviar("PUT", { estado, nota, empresa, proyecto })); await cargar(); onCambio?.(); }
    catch (e) { setError(e); }
  };
  const quitar = async () => {
    try { await pedirCerebro(`subvenciones/oportunidades/${id}/guardada`, { method: "DELETE" }); await cargar(); onCambio?.(); }
    catch (e) { setError(e); }
  };
  if (error && !d) return <section className="tarjeta"><p className="aviso" role="alert">{mensajeError(error)}</p><button className="boton no" onClick={onCerrar}>Cerrar</button></section>;
  if (!d) return <section className="tarjeta"><p>Cargando…</p></section>;
  const enlace = urlSegura(d.official_url);
  const solicitud = urlSegura(d.application_url);
  return (
    <section className="tarjeta" aria-label="Ficha de la oportunidad">
      <p className="lic-fila"><button className="boton no" onClick={onCerrar}>← Volver</button></p>
      <h2>{d.title}</h2>
      {error && <p className="aviso" role="alert">{mensajeError(error)}</p>}
      <p className="lic-fila">
        <span className={`lic-etiqueta ${ESTADO_CLASE[d.status] || ""}`}>{ESTADO_ETIQUETA[d.status] || d.status}</span>
        {d.funding_type && <span className="lic-etiqueta">{INSTRUMENTO_ETIQUETA[d.funding_type] || d.funding_type}</span>}
        <span className="meta">{plazoTexto(d.deadline)}</span>
      </p>
      <dl className="lic-ficha">
        {[["Organismo", d.issuing_organization], ["Programa", d.program_name], ["País / región", [d.country, d.region, d.province].filter(Boolean).join(" · ")],
          ["Presupuesto total", importeTexto(d.total_budget, d.currency)], ["Importe máximo", importeTexto(d.maximum_amount, d.currency)],
          ["Publicación", fechaCorta(d.publication_date)], ["Apertura", fechaCorta(d.opening_date)], ["Fin del plazo", fechaCorta(d.deadline)],
          ["Beneficiarios", (d.eligible_beneficiaries || []).join(", ")], ["Sectores", (d.sector || []).join(", ")],
          ["Requisitos", d.eligibility_requirements], ["Gastos subvencionables", d.eligible_expenses], ["Exclusiones", d.exclusions],
          ["Última comprobación", haceTexto(d.last_checked_at)]].filter(([, v]) => v && v !== "—").map(([k, v]) => <div key={k}><dt>{k}</dt><dd style={{ whiteSpace: "pre-line" }}>{String(v)}</dd></div>)}
      </dl>
      {d.description && <p style={{ whiteSpace: "pre-line" }}>{d.description}</p>}
      <Analisis id={id} />
      <Bases id={id} />
      <p className="meta">Los datos vienen de la fuente oficial y se muestran tal cual: compruébalos en la convocatoria antes de decidir. No se ha evaluado si encaja con tu empresa.</p>
      <p className="lic-fila">
        {enlace && <a className="boton no" href={enlace} target="_blank" rel="noopener noreferrer">Ver en la fuente oficial</a>}
        {solicitud && <a className="boton no" href={solicitud} target="_blank" rel="noopener noreferrer">Solicitud</a>}
      </p>
      {d.fuentes?.length > 0 && <>
        <h3>Procedencia</h3>
        <ul className="lic-lista">{d.fuentes.map((s) => <li key={s.source_code + s.external_id} className="meta">{s.source_name} · {s.external_id} · visto por última vez {haceTexto(s.last_seen)}</li>)}</ul>
      </>}
      {d.documentos?.length > 0 && <>
        <h3>Documentos</h3>
        <ul className="lic-lista">{d.documentos.map((x, i) => <li key={i}>{urlSegura(x.url) ? <a href={urlSegura(x.url)} target="_blank" rel="noopener noreferrer">{x.title || x.url}</a> : (x.title || "Documento")}</li>)}</ul>
      </>}
      {d.historial?.length > 0 && <>
        <h3>Historial de cambios</h3>
        <ul className="lic-lista">{d.historial.slice(0, 15).map((h, i) => <li key={i} className="meta">{haceTexto(h.changed_at)} · {h.field}: {String(h.old_value ?? "—").slice(0, 60)} → {String(h.new_value ?? "—").slice(0, 60)}</li>)}</ul>
      </>}
      <h3>Mi seguimiento</h3>
      <p className="lic-fila">
        <input value={empresa} onChange={(e) => setEmpresa(e.target.value)} placeholder="Empresa (opcional)" maxLength={200} aria-label="Empresa" />
        <input value={proyecto} onChange={(e) => setProyecto(e.target.value)} placeholder="Proyecto (opcional)" maxLength={200} aria-label="Proyecto" />
      </p>
      <textarea value={nota} onChange={(e) => setNota(e.target.value)} placeholder="Nota" maxLength={2000} rows={3} aria-label="Nota" style={{ width: "100%" }} />
      <p className="lic-fila">
        <button className="boton si" onClick={() => guardar("seguida")}>{d.guardada?.estado === "seguida" ? "Actualizar seguimiento" : "Seguir"}</button>
        <button className="boton no" onClick={() => guardar("descartada")}>Descartar</button>
        {d.guardada && <button className="boton no" onClick={quitar}>Quitar de mis oportunidades</button>}
        {d.guardada && <span className="meta">Ahora: {d.guardada.estado}</span>}
      </p>
    </section>
  );
}

function Radar({ abrir }) {
  const [d, setD] = useState(undefined);
  const [error, setError] = useState(null);
  useEffect(() => { pedirCerebro("subvenciones/radar").then(setD).catch((e) => { setError(e); setD(null); }); }, []);
  if (d === undefined) return <p>Cargando…</p>;
  if (!d) return <p className="aviso" role="alert">{mensajeError(error)}</p>;
  const vacio = CATEGORIAS_RADAR.every(([k]) => !d[k]?.total);
  return (
    <>
      <p className="meta">Última sincronización correcta de una fuente activa: {d.ultima_sincronizacion_correcta ? haceTexto(d.ultima_sincronizacion_correcta) : "ninguna todavía"}.</p>
      {vacio && <p className="aviso" role="status">Todavía no hay oportunidades. Dirección debe verificar y activar un conector en la pestaña «Conectores» (una sincronización manual correcta antes de activarlo).</p>}
      {CATEGORIAS_RADAR.map(([k, nombre]) => (
        <section key={k} className="tarjeta" aria-label={nombre}>
          <h2>{nombre} <span className="lic-etiqueta">{d[k]?.total ?? 0}</span></h2>
          {d[k]?.oportunidades?.length ? <ul className="lic-lista">{d[k].oportunidades.map((o) => <Fila key={o.id} o={o} onAbrir={abrir} />)}</ul> : <p className="meta">Nada por ahora.</p>}
        </section>
      ))}
      <section className="tarjeta"><h2>Relevantes para tu empresa</h2><p className="meta">{d.relevantes_para_tu_empresa?.nota}</p></section>
    </>
  );
}

function Buscador({ abrir }) {
  const [f, setF] = useState(FILTROS_VACIOS);
  const [pagina, setPagina] = useState(0);
  const [r, setR] = useState(null);
  const [error, setError] = useState(null);
  const [cargando, setCargando] = useState(false);
  const buscar = useCallback(async (filtros, pag) => {
    setCargando(true);
    try { setR(await pedirCerebro(`subvenciones/oportunidades${filtrosAQuery(filtros, pag)}`)); setError(null); }
    catch (e) { setError(e); } finally { setCargando(false); }
  }, []);
  useEffect(() => { buscar(FILTROS_VACIOS, 0); }, [buscar]);
  const cambia = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <>
      <p className="lic-fila" role="group" aria-label="Estado de la convocatoria">
        {GRUPOS_ESTADO.map((g) => <button key={g.clave} type="button" className={`boton ${grupoActivo(f.estado) === g.clave ? "si" : "no"}`} aria-pressed={grupoActivo(f.estado) === g.clave}
          onClick={() => { const n = { ...f, estado: g.estados }; setF(n); setPagina(0); buscar(n, 0); }}>{g.nombre}</button>)}
        <button type="button" className={`boton ${f.estado.length === 0 ? "si" : "no"}`} onClick={() => { const n = { ...f, estado: "" }; setF(n); setPagina(0); buscar(n, 0); }}>Todas</button>
      </p>
      <form className="tarjeta" onSubmit={(e) => { e.preventDefault(); setPagina(0); buscar(f, 0); }}>
        <p className="lic-fila">
          <input value={f.texto} onChange={cambia("texto")} placeholder="Palabras (p. ej. digitalización)" aria-label="Texto" />
          <select value={f.instrumento} onChange={cambia("instrumento")} aria-label="Instrumento"><option value="">Cualquier instrumento</option>{Object.entries(INSTRUMENTO_ETIQUETA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <input value={f.pais} onChange={cambia("pais")} placeholder="País (ES, AD…)" maxLength={3} aria-label="País" style={{ width: "6rem" }} />
        </p>
        <p className="lic-fila">
          <input value={f.importeMin} onChange={cambia("importeMin")} placeholder="Importe mín. (€)" inputMode="decimal" aria-label="Importe mínimo" />
          <input value={f.importeMax} onChange={cambia("importeMax")} placeholder="Importe máx. (€)" inputMode="decimal" aria-label="Importe máximo" />
          <label>Plazo desde <input type="date" value={f.plazoDesde} onChange={cambia("plazoDesde")} /></label>
          <label>hasta <input type="date" value={f.plazoHasta} onChange={cambia("plazoHasta")} /></label>
          <label><input type="checkbox" checked={f.soloNuevas} onChange={cambia("soloNuevas")} /> Solo nuevas</label>
          <select value={f.orden} onChange={cambia("orden")} aria-label="Orden"><option value="">Orden por defecto</option><option value="plazo">Plazo</option><option value="nueva">Más recientes</option><option value="importe">Importe</option><option value="relevancia">Relevancia</option></select>
        </p>
        <p className="lic-fila"><button className="boton si" disabled={cargando}>Buscar</button><button type="button" className="boton no" onClick={() => { setF(FILTROS_VACIOS); setPagina(0); buscar(FILTROS_VACIOS, 0); }}>Limpiar</button></p>
      </form>
      {error && <p className="aviso" role="alert">{mensajeError(error)}</p>}
      {r && (
        <section aria-label="Resultados">
          <p className="meta">{r.total} resultado{r.total === 1 ? "" : "s"}</p>
          <ul className="lic-lista">{r.resultados.map((o) => <Fila key={o.id} o={o} onAbrir={abrir} />)}</ul>
          <p className="lic-fila">
            <button className="boton no" disabled={pagina <= 0 || cargando} onClick={() => { setPagina(pagina - 1); buscar(f, pagina - 1); }}>← Anterior</button>
            <span className="meta">Página {pagina + 1}</span>
            <button className="boton no" disabled={(pagina + 1) * 25 >= r.total || cargando} onClick={() => { setPagina(pagina + 1); buscar(f, pagina + 1); }}>Siguiente →</button>
          </p>
        </section>
      )}
    </>
  );
}

function Mias({ abrir, version }) {
  const [lista, setLista] = useState(undefined);
  const [error, setError] = useState(null);
  useEffect(() => { pedirCerebro("subvenciones/mis-oportunidades").then(setLista).catch((e) => { setError(e); setLista([]); }); }, [version]);
  if (lista === undefined) return <p>Cargando…</p>;
  return (
    <>
      {error && <p className="aviso" role="alert">{mensajeError(error)}</p>}
      {lista.length === 0 ? <p className="meta">Aún no sigues ninguna oportunidad. Ábrela desde el Radar o el Buscador y pulsa «Seguir».</p>
        : <ul className="lic-lista">{lista.map((o) => (
          <div key={o.id}><Fila o={o} onAbrir={abrir} /><p className="meta">{o.guardada === "descartada" ? "Descartada" : "Seguida"}{o.empresa ? ` · ${o.empresa}` : ""}{o.proyecto ? ` · ${o.proyecto}` : ""}{o.nota ? ` · ${o.nota}` : ""}</p></div>
        ))}</ul>}
    </>
  );
}

function Conectores() {
  const [lista, setLista] = useState(undefined);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const cargar = useCallback(async () => {
    try { setLista(await pedirCerebro("subvenciones/fuentes")); setError(null); }
    catch (e) { setError(e); setLista(null); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  const hacer = async (fn, ok) => {
    setTrabajando(true); setError(null); setAviso(null);
    try { await fn(); if (ok) setAviso(ok); await cargar(); } catch (e) { setError(e); } finally { setTrabajando(false); if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" }); }   // el aviso o el error salen arriba: se sube para que se vean
  };
  if (lista === undefined) return <p>Cargando…</p>;
  if (lista === null) return <p className="aviso" role="alert">{mensajeError(error)}</p>;
  return (
    <>
      <p className="meta">Un conector se activa solo después de una sincronización manual correcta con datos reales. La lectura es solo de consulta: este módulo no presenta solicitudes ni escribe en las fuentes.</p>
      {error && <p className="aviso" role="alert">{mensajeError(error)}</p>}
      {aviso && <p className="aviso" role="status">{aviso}</p>}
      <ul className="lic-lista">{lista.map((f) => {
        const motivo = activableMotivo(f);
        return (
          <li key={f.source_code} className="tarjeta lic-item">
            <span className="lic-fila"><strong>{f.source_code} · {f.source_name}</strong>
              <span className="lic-etiqueta">{ESTADO_FUENTE[f.integration_status] || f.integration_status}</span>
              <span className={`lic-etiqueta ${f.is_enabled ? "ok" : ""}`}>{f.is_enabled ? "Habilitada" : "Deshabilitada"}</span></span>
            <span className="meta">{f.country} · {f.geographic_scope} · {f.access_type} · {f.has_connector ? "con conector" : "sin conector"} · {f.records} registros</span>
            <span className="meta">Última sincronización {haceTexto(f.last_sync_at)} · correcta {haceTexto(f.last_success_at)} · {ejecucionTexto(f)}</span>
            {f.last_error && <span className="aviso" role="alert">Error: {String(f.last_error).slice(0, 200)}</span>}
            <span className="lic-fila">
              <button className="boton no" disabled={trabajando || !f.has_connector} onClick={() => hacer(() => pedirCerebro(`subvenciones/fuentes/${f.source_code}/sincronizar`, enviar("POST")), "Sincronización lanzada: en un minuto, pulsa «Actualizar».")}>Sincronizar ahora</button>
              {f.is_enabled
                ? <button className="boton no" disabled={trabajando} onClick={() => hacer(() => pedirCerebro(`subvenciones/fuentes/${f.source_code}`, enviar("PATCH", { habilitada: false })), "Fuente pausada.")}>Pausar</button>
                : <button className="boton si" disabled={trabajando || !!motivo} title={motivo} onClick={() => hacer(() => pedirCerebro(`subvenciones/fuentes/${f.source_code}`, enviar("PATCH", { habilitada: true })), "Fuente activada.")}>Activar</button>}
              {motivo && !f.is_enabled && <span className="meta">{motivo}</span>}
            </span>
          </li>
        );
      })}</ul>
      <p><button className="boton no" onClick={cargar}>Actualizar</button></p>
    </>
  );
}

export default function Subvenciones() {
  const [pestana, setPestana] = useState("radar");
  const [abierta, setAbierta] = useState(null);
  const [version, setVersion] = useState(0);
  const abrir = (id) => setAbierta(id);
  return (
    <main className="lic">
      <h1>Subvenciones y financiación</h1>
      <p className="meta">Radar de ayudas oficiales (España, Andorra y Unión Europea). Son datos públicos de fuentes oficiales; el sistema los lee y los ordena, pero no decide si te convienen ni presenta solicitudes.</p>
      {abierta ? <Ficha id={abierta} onCerrar={() => setAbierta(null)} onCambio={() => setVersion((v) => v + 1)} /> : (
        <>
          <p className="lic-fila" role="tablist">{PESTANAS.map(([k, n]) => <button key={k} role="tab" aria-selected={pestana === k} className={`boton ${pestana === k ? "si" : "no"}`} onClick={() => setPestana(k)}>{n}</button>)}</p>
          {pestana === "radar" && <Radar abrir={abrir} />}
          {pestana === "buscar" && <Buscador abrir={abrir} />}
          {pestana === "mias" && <Mias abrir={abrir} version={version} />}
          {pestana === "fuentes" && <Conectores />}
        </>
      )}
    </main>
  );
}
