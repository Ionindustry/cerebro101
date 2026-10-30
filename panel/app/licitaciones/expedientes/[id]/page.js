"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Redaccion from "./Redaccion";
import { SOBRES_OFERTA, autorSeccionTexto, claseSeccion, estadoSeccionEtiqueta, mensajeOferta, pendientesOferta, precioAEnvio, resumenOfertaTexto, FORMULAS_PRECIO, costeErpTexto, mensajeReglas, reglasAEnvio, reglasAFormulario, cercaniaTexto, mensajeParecidas, motivosTexto, aptitudSimulacion, costeDeTexto, filasDeCurva, mensajeSimulador, probabilidadConRango, porcentaje, CUMPLIMIENTOS, cumplimientoEtiqueta, cumplimientoNecesitaNota, estadoEtiqueta, estadoPliego, estadoRequisito, etiquetaEmbudo, fechaTexto, fichaOrgHref, importeTexto, lecturaPliego, lugarCita, matrizCsv, matrizDe, mensajeEmbudo, mensajePliegos, resumenMatriz, nombreFuente, puedeDescargarPliego, resumenRequisitos, tipoRequisito, urlSegura } from "../../../../lib/licitaciones";
import { Fallo, Item, pedir, pedirCerebro } from "../../cliente";

const Dato = ({ t, children }) => <div><dt>{t}</dt><dd>{children ?? "—"}</dd></div>;
const Enlace = ({ url, children }) => {
  const u = urlSegura(url);
  return u ? <a href={u} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
};

// «Estudiar»: pasa el expediente al embudo de 101.cat. Solo lo ven Dirección y Licitaciones (para los demás la consulta da 403 y la tarjeta no aparece).
function Estudiar({ id }) {
  const [fila, setFila] = useState(undefined);        // undefined = consultando; null = no está en el embudo
  const [permitido, setPermitido] = useState(true);
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    pedirCerebro(`licitaciones/embudo?motor_id=${encodeURIComponent(id)}`).then((l) => setFila(l.items[0] || null)).catch(() => setPermitido(false));
  }, [id]);
  if (!permitido || fila === undefined) return null;
  const estudiar = async () => {
    setTrabajando(true); setError(null);
    try { setFila(await pedirCerebro("licitaciones/embudo/estudiar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motor_id: id }) })); }
    catch (e) { setError(e); }
    finally { setTrabajando(false); }
  };
  return (
    <section className="tarjeta" aria-label="Embudo">
      <h2>Embudo de 101.cat</h2>
      {fila ? (
        <p>Estado: <span className="lic-etiqueta">{etiquetaEmbudo(fila.estado)}</span> · <Link href="/licitaciones/embudo">Ver el embudo</Link></p>
      ) : (
        <>
          <p className="meta">Si te interesa, pásala a estudio: se anota en el embudo y Viabilidad podrá valorarla. No se presenta nada por ti.</p>
          <button className="boton si" onClick={estudiar} disabled={trabajando}>{trabajando ? "Anotando…" : "Estudiar"}</button>
        </>
      )}
      {error && <p role="alert" className="lic-error">{mensajeEmbudo(error.status)}</p>}
    </section>
  );
}

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

// Pliegos: los documentos de la licitación (se bajan a cuarentena y pasan por el antivirus, nadie recibe el fichero) y los requisitos que ha anotado el Analista de Pliegos con su cita.
// Los confirma o rechaza una persona. Solo Dirección y Licitaciones (para los demás la consulta da 403 y la tarjeta no aparece).
function Cumplimiento({ r, onCumplir, trabajando }) {
  const [estado, setEstado] = useState(r.cumplimiento || "pendiente");
  const [nota, setNota] = useState(r.cumplimiento_nota || "");
  const necesita = cumplimientoNecesitaNota(estado);
  const e = cumplimientoEtiqueta(r.cumplimiento || "pendiente");
  const sinCambios = estado === (r.cumplimiento || "pendiente") && nota === (r.cumplimiento_nota || "");
  return (
    <span className="lic-fila" role="group" aria-label="Cumplimiento">
      <span className={`lic-etiqueta ${e.clase}`}>{e.texto}</span>
      <select value={estado} onChange={(x) => setEstado(x.target.value)} aria-label="¿Cumple 101.cat este requisito?">
        {Object.entries(CUMPLIMIENTOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {(necesita || nota) && <input type="text" value={nota} maxLength={500} onChange={(x) => setNota(x.target.value)} placeholder={necesita ? "¿Por qué? (obligatorio)" : "Nota (opcional)"} aria-label="Motivo o nota" />}
      <button className="boton si" disabled={trabajando || sinCambios || (necesita && nota.trim().length < 5)} onClick={() => onCumplir(r.id, estado, nota)}>Guardar cumplimiento</button>
      {r.cumplimiento_por && <span className="meta">Valorado por {r.cumplimiento_por} el {fechaTexto(r.cumplimiento_en)}</span>}
    </span>
  );
}

function Requisito({ r, onRevisar, onCumplir, trabajando }) {
  const [pagina, setPagina] = useState(null);       // texto de la página citada, si se ha abierto
  const [errorPagina, setErrorPagina] = useState(null);
  const e = estadoRequisito(r);
  const ver = async () => {
    if (pagina) { setPagina(null); return; }
    setErrorPagina(null);
    try { setPagina(await pedirCerebro(`licitaciones/pliegos/${encodeURIComponent(r.motor_id)}/documentos/${r.documento}/paginas/${r.pagina}`)); }
    catch (x) { setErrorPagina(x); }
  };
  return (
    <li className="tarjeta lic-item">
      <span className="lic-fila">
        <span className="lic-etiqueta">{tipoRequisito(r.tipo)}</span>
        <span className={`lic-etiqueta ${e.clase}`}>{e.texto}</span>
        {r.valor && <span className="meta">{r.valor}</span>}
      </span>
      <span>{r.resumen}</span>
      <blockquote className="meta">«{r.cita}»<br />{lugarCita(r)}</blockquote>
      <span className="lic-fila">
        <button className="boton no" onClick={ver}>{pagina ? "Ocultar la página" : "Ver la página"}</button>
        {r.estado !== "confirmado" && <button className="boton si" disabled={trabajando} onClick={() => onRevisar(r.id, "confirmado")}>Confirmar</button>}
        {r.estado !== "rechazado" && <button className="boton no" disabled={trabajando} onClick={() => onRevisar(r.id, "rechazado")}>Rechazar</button>}
        {r.estado !== "borrador" && <button className="boton no" disabled={trabajando} onClick={() => onRevisar(r.id, "borrador")}>Volver a borrador</button>}
        {r.revisado_por && <span className="meta">Revisado por {r.revisado_por} el {fechaTexto(r.revisado)}</span>}
      </span>
      {r.estado === "confirmado" && <Cumplimiento key={`${r.cumplimiento}|${r.cumplimiento_nota}`} r={r} onCumplir={onCumplir} trabajando={trabajando} />}
      {errorPagina && <p role="alert" className="lic-error">{mensajePliegos(errorPagina.status)}</p>}
      {pagina && (
        <details open className="lic-informe">
          <summary>Texto de la {pagina.unidad} {pagina.pagina} de {pagina.de}</summary>
          <p className="meta">Texto de un documento de terceros, tal como se ha leído: puede tener errores de lectura.</p>
          <pre className="lic-informe-texto">{pagina.texto}</pre>
        </details>
      )}
    </li>
  );
}

function Pliegos({ id }) {
  const [d, setD] = useState(undefined);              // undefined = consultando; null = sin acceso
  const [error, setError] = useState(null);
  const [trabajando, setTrabajando] = useState(null);  // número del documento que se está bajando, o "revisando"
  const cargar = async () => {
    try { setD(await pedirCerebro(`licitaciones/pliegos/${encodeURIComponent(id)}`)); setError(null); }
    catch (e) { if (e.status === 403 || e.status === 401) setD(null); else { setError(e); setD((x) => (x === undefined ? null : x)); } }
  };
  useEffect(() => { cargar(); }, [id]);
  if (!d && !error) return null;
  const bajar = async (n) => {
    setTrabajando(n); setError(null);
    try { await pedirCerebro(`licitaciones/pliegos/${encodeURIComponent(id)}/descargar`, enviar({ n })); await cargar(); }
    catch (e) { setError(e); await cargar(); }
    finally { setTrabajando(null); }
  };
  const revisar = async (rid, estado) => {
    setTrabajando("revisando"); setError(null);
    try { await pedirCerebro(`licitaciones/pliegos/requisitos/${rid}/revisar`, enviar({ estado })); await cargar(); }
    catch (e) { setError(e); }
    finally { setTrabajando(null); }
  };
  const cumplir = async (rid, estado, nota) => {
    setTrabajando("revisando"); setError(null);
    try { await pedirCerebro(`licitaciones/pliegos/requisitos/${rid}/cumplimiento`, enviar({ estado, nota })); await cargar(); }
    catch (e) { setError(e); }
    finally { setTrabajando(null); }
  };
  const descargarMatriz = () => {
    const url = URL.createObjectURL(new Blob([matrizCsv(matrizDe(d?.requisitos))], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = "matriz-de-cumplimiento.csv"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const docs = d?.documentos || [], reqs = (d?.requisitos || []).map((r) => ({ ...r, motor_id: id }));
  return (
    <section className="tarjeta" aria-label="Pliegos">
      <h2>Pliegos</h2>
      <p className="meta">Los documentos se bajan a cuarentena y pasan por el antivirus antes de leerse; nadie recibe el fichero original, solo su texto. Los requisitos los anota un agente de IA con su cita literal y una persona los confirma o rechaza.</p>
      {error && <p role="alert" className="lic-error">{mensajePliegos(error.status)}</p>}
      {docs.length === 0 && d && <p className="meta">Esta licitación no tiene documentos publicados.</p>}
      <ul className="lic-lista">
        {docs.map((x) => {
          const e = estadoPliego(x.descarga), lectura = lecturaPliego(x.descarga);
          return (
            <li key={x.n} className="tarjeta lic-item">
              <span className="lic-fila"><span className="titulo">{x.nombre}</span><span className={`lic-etiqueta ${e.clase}`}>{e.texto}</span></span>
              {lectura && <span className="meta">{lectura}</span>}
              {x.descarga?.motivo && <span className="meta">{x.descarga.motivo}</span>}
              {puedeDescargarPliego(x.descarga) && <span className="lic-fila"><button className="boton no" disabled={trabajando !== null} onClick={() => bajar(x.n)}>{trabajando === x.n ? "Descargando y analizando…" : x.descarga ? "Reintentar" : "Descargar y analizar"}</button></span>}
            </li>
          );
        })}
      </ul>
      <h3>Requisitos <span className="meta">· {resumenRequisitos(reqs)}</span></h3>
      {reqs.length > 0 && <ul className="lic-lista">{reqs.map((r) => <Requisito key={r.id} r={r} onRevisar={revisar} onCumplir={cumplir} trabajando={trabajando !== null} />)}</ul>}
      {(() => {
        const m = matrizDe(reqs);
        if (!m.total) return null;
        return (
          <>
            <h3>Matriz de cumplimiento <span className="meta">· {resumenMatriz(m)}</span></h3>
            {m.borradores > 0 && <p className="meta">Quedan {m.borradores} {m.borradores === 1 ? "requisito" : "requisitos"} en borrador sin revisar: la matriz está incompleta.</p>}
            <p className="meta">La matriz son los requisitos confirmados, cada uno con su cita. Quien prepare la oferta valora aquí si 101.cat los cumple; «parcial» y «no cumple» llevan su motivo.</p>
            <span className="lic-fila"><button className="boton no" onClick={descargarMatriz}>Descargar la matriz (CSV)</button></span>
          </>
        );
      })()}
    </section>
  );
}

// La oferta: el borrador por secciones (sobres administrativo, técnico y económico). Los agentes solo dejan borradores; revisar, aprobar, fijar el precio y presentar lo hace una persona.
function SeccionOferta({ s, motorId, alCambiar }) {
  const [texto, setTexto] = useState(s.contenido || "");
  const [msg, setMsg] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  useEffect(() => { setTexto(s.contenido || ""); }, [s.contenido, s.version]);
  const economica = s.sobre === "economico" && s.clave === "proposicion-economica";
  const cambiado = texto.trim() !== (s.contenido || "").trim();
  const guardar = async () => {
    setTrabajando(true); setMsg(null);
    try { await pedirCerebro("licitaciones/ofertas/seccion", enviar({ motor_id: motorId, sobre: s.sobre, clave: s.clave, contenido: texto })); await alCambiar(); }
    catch (e) { setMsg(mensajeOferta(e.status, e.detalle)); } finally { setTrabajando(false); }
  };
  const estado = async (nuevo) => {
    setTrabajando(true); setMsg(null);
    try { await pedirCerebro(`licitaciones/ofertas/seccion/${s.id}/estado`, enviar({ estado: nuevo })); await alCambiar(); }
    catch (e) { setMsg(mensajeOferta(e.status, e.detalle)); } finally { setTrabajando(false); }
  };
  return (
    <details className="lic-informe" open={s.estado === "vacia" || undefined}>
      <summary><strong>{s.titulo}</strong> <span className={`lic-etiqueta ${claseSeccion(s.estado)}`}>{estadoSeccionEtiqueta(s.estado)}</span></summary>
      {s.guia && <p className="meta" style={{ whiteSpace: "pre-line" }}>{s.guia}</p>}
      {economica
        ? <p className="meta">Esta sección se genera sola con el precio que fijes arriba (o con el modelo oficial del pliego, si lo hay).</p>
        : (
          <>
            <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={10} maxLength={60000} aria-label={`Contenido de ${s.titulo}`} style={{ width: "100%" }} placeholder="Sin redactar todavía. Escríbela o pide a los agentes que la redacten." />
            <div className="lic-fila">
              <button className="boton si" onClick={guardar} disabled={trabajando || !cambiado}>Guardar</button>
              {s.estado === "borrador" && !cambiado && <button className="boton no" onClick={() => estado("revisada")} disabled={trabajando}>Marcar como revisada</button>}
              {(s.estado === "borrador" || s.estado === "revisada") && !cambiado && <button className="boton no" onClick={() => estado("aprobada")} disabled={trabajando}>Aprobar</button>}
              {(s.estado === "revisada" || s.estado === "aprobada") && <button className="boton no" onClick={() => estado("borrador")} disabled={trabajando}>Volver a borrador</button>}
              <span className="meta">{[autorSeccionTexto(s), s.revisado_por ? `${estadoSeccionEtiqueta(s.estado)} por ${s.revisado_por}` : "", s.citas?.length ? `cita ${s.citas.length} requisito${s.citas.length === 1 ? "" : "s"} del pliego` : ""].filter(Boolean).join(" · ")}</span>
            </div>
          </>
        )}
      {msg && <p role="alert" className="lic-error">{msg}</p>}
    </details>
  );
}

function Oferta({ id }) {
  const [o, setO] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const [precio, setPrecio] = useState({ precio: "", iva: "" });
  const cargar = async () => {
    try { const r = await pedirCerebro(`licitaciones/ofertas/${id}`); setO(r); setError(null); if (r.precio_sin_iva != null) setPrecio({ precio: String(r.precio_sin_iva).replace(".", ","), iva: String(r.iva_pct) }); }
    catch (e) { setError(e); }
  };
  useEffect(() => { cargar(); }, [id]);          // eslint-disable-line react-hooks/exhaustive-deps
  if (error && (error.status === 403 || error.status === 401)) return null;        // para los demás grupos, la tarjeta no aparece
  const accion = async (f) => { setTrabajando(true); setMsg(null); try { await f(); await cargar(); } catch (e) { setMsg(mensajeOferta(e.status, e.detalle)); } finally { setTrabajando(false); } };
  const preparar = () => accion(() => pedirCerebro(`licitaciones/ofertas/${id}/preparar`, { method: "POST" }));
  const fijarPrecio = () => {
    const { cuerpo, error: err } = precioAEnvio(precio);
    if (err) { setMsg(err); return; }
    accion(() => pedirCerebro(`licitaciones/ofertas/${id}/precio`, enviar(cuerpo)));
  };
  const descargar = () => accion(async () => {
    const d = await pedirCerebro(`licitaciones/ofertas/${id}/documento`);
    const bytes = Uint8Array.from(atob(d.base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: d.tipo }));
    const a = document.createElement("a"); a.href = url; a.download = d.nombre; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });
  const pendientes = pendientesOferta(o);
  return (
    <section className="tarjeta" aria-label="Oferta">
      <h2>Oferta</h2>
      <p className="meta">El borrador de la oferta, por sobres. Los agentes solo escriben <strong>borradores</strong> a partir de los requisitos del pliego que hayas confirmado; tú los revisas, apruebas y fijas el precio. Nada se presenta desde aquí: se exporta a Word para revisarlo, firmarlo y presentarlo.</p>
      {error && !o && <p role="alert" className="lic-error">{mensajeOferta(error.status, error.detalle)}</p>}
      {o && !o.existe && (
        <>
          <Redaccion id={id} o={o} alCambiar={cargar} />
          <div className="lic-fila">
            <button className="boton no" onClick={preparar} disabled={trabajando}>{trabajando ? "Preparando…" : "Solo crear las secciones (sin agentes)"}</button>
            <span className="ayuda">Mejor después de leer el pliego y confirmar sus requisitos (tarjeta «Pliegos»): las secciones salen de ahí.</span>
          </div>
        </>
      )}
      {o?.existe && (
        <>
          <Redaccion id={id} o={o} alCambiar={cargar} />
          <p><strong>{resumenOfertaTexto(o)}</strong></p>
          {pendientes.length > 0 && <p className="meta">Falta: {pendientes.join("; ")}.</p>}
          <div className="lic-fila">
            <label>Precio de la oferta, sin IVA (€)<input type="text" inputMode="decimal" value={precio.precio} onChange={(e) => setPrecio((x) => ({ ...x, precio: e.target.value }))} placeholder="125.000,50" /></label>
            <label>IVA (%)<input type="text" inputMode="decimal" value={precio.iva} onChange={(e) => setPrecio((x) => ({ ...x, iva: e.target.value }))} placeholder="21" size={4} /></label>
            <button className="boton no" onClick={fijarPrecio} disabled={trabajando}>Fijar precio</button>
            <button className="boton si" onClick={descargar} disabled={trabajando}>Descargar en Word</button>
            <button className="boton no" onClick={preparar} disabled={trabajando} title="Añade las secciones que falten si has confirmado más requisitos; no toca lo ya escrito">Actualizar secciones</button>
          </div>
          <p className="meta">El precio lo decides tú (el simulador de arriba te ayuda); con él se genera la proposición económica. {o.precio_por ? `Fijado por ${o.precio_por}.` : "Aún sin fijar."}</p>
          {SOBRES_OFERTA.map(([sobre, titulo]) => {
            const secs = o.secciones.filter((x) => x.sobre === sobre);
            return secs.length === 0 ? null : (
              <div key={sobre}>
                <h3>{titulo}</h3>
                {secs.map((x) => <SeccionOferta key={x.id} s={x} motorId={id} alCambiar={cargar} />)}
              </div>
            );
          })}
        </>
      )}
      {msg && <p role="alert" className="lic-error">{msg}</p>}
    </section>
  );
}

function Parecidas({ id }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let vivo = true;
    setItems(null); setError(null);
    pedir(`tenders/${id}/parecidas?limit=8`).then((d) => { if (vivo) setItems(d.items); }).catch((e) => { if (vivo) setError(e); });
    return () => { vivo = false; };
  }, [id]);
  return (
    <section className="tarjeta" aria-label="Licitaciones parecidas">
      <h2>Licitaciones parecidas</h2>
      <p className="meta">Las más cercanas en significado, aunque no usen las mismas palabras. Que se parezcan no quiere decir que sean el mismo contrato.</p>
      {error && <p role="alert" className="lic-error">{mensajeParecidas(error.status)}</p>}
      {!error && items === null && <p className="meta">Buscando…</p>}
      {items && items.length === 0 && <p className="meta">No se han encontrado licitaciones parecidas.</p>}
      {items && items.length > 0 && <ul className="lic-lista">{items.map((x) => <Item key={x.id} x={x} />)}</ul>}
    </section>
  );
}

// Las reglas con las que el pliego puntúa el precio: las anota una persona leyendo el pliego (el agente no). Con ellas el simulador calcula los puntos de precio de cada oferta y usa el umbral de baja anormal del pliego.
function ReglasPrecio({ id, alGuardar }) {
  const [f, setF] = useState(reglasAFormulario(null));
  const [hay, setHay] = useState(false);
  const [msg, setMsg] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  useEffect(() => {
    let vivo = true;
    pedirCerebro(`licitaciones/reglas-precio/${id}`).then((r) => { if (vivo && r?.formula) { setF(reglasAFormulario(r)); setHay(true); } }).catch(() => {});
    return () => { vivo = false; };
  }, [id]);
  const poner = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const guardar = async (ev) => {
    ev.preventDefault();
    const { cuerpo, error } = reglasAEnvio(id, f);
    if (error) { setMsg({ error }); return; }
    setTrabajando(true); setMsg(null);
    try { await pedirCerebro("licitaciones/reglas-precio", enviar(cuerpo)); setHay(true); setMsg({ ok: "Reglas guardadas. Vuelve a simular para usarlas." }); alGuardar?.(); }
    catch (e) { setMsg({ error: mensajeReglas(e.status) }); }
    finally { setTrabajando(false); }
  };
  const quitar = async () => {
    setTrabajando(true); setMsg(null);
    try { await pedirCerebro(`licitaciones/reglas-precio/${id}/borrar`, { method: "POST" }); setF(reglasAFormulario(null)); setHay(false); setMsg({ ok: "Reglas quitadas." }); alGuardar?.(); }
    catch (e) { setMsg({ error: mensajeReglas(e.status) }); }
    finally { setTrabajando(false); }
  };
  return (
    <details className="lic-informe">
      <summary>Reglas de puntuación del pliego {hay ? "(anotadas)" : "(opcional)"}</summary>
      <p className="meta">Mira en el pliego el apartado de criterios de adjudicación y copia aquí cómo puntúa el precio. Con eso el simulador calcula los puntos de precio de cada oferta y usa el umbral de baja anormal del pliego en vez de estimarlo. Las anotas tú: la IA no las toca.</p>
      <form className="lic-form" onSubmit={guardar}>
        <div className="lic-campos">
          <label>Fórmula del precio
            <select value={f.formula} onChange={poner("formula")}>{FORMULAS_PRECIO.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
          </label>
          <label>Puntos del precio<input type="text" inputMode="decimal" value={f.puntos} onChange={poner("puntos")} placeholder="51" /></label>
          <label>Puntos totales<input type="text" inputMode="decimal" value={f.total} onChange={poner("total")} placeholder="100" /></label>
          {f.formula === "lineal_umbral" && <label>Baja tope (%)<input type="text" inputMode="decimal" value={f.tope} onChange={poner("tope")} placeholder="20" /></label>}
          <label>Baja anormal desde (%)<input type="text" inputMode="decimal" value={f.anormal} onChange={poner("anormal")} placeholder="si el pliego lo fija" /></label>
          <label>Nota (dónde lo dice el pliego)<input type="text" value={f.nota} onChange={poner("nota")} maxLength={500} placeholder="Cláusula 12, p. 18" /></label>
        </div>
        <div className="lic-fila">
          <button className="boton si" type="submit" disabled={trabajando}>Guardar reglas</button>
          {hay && <button className="boton no" type="button" onClick={quitar} disabled={trabajando}>Quitar</button>}
        </div>
        {msg?.error && <p role="alert" className="lic-error">{msg.error}</p>}
        {msg?.ok && <p role="status" className="meta">{msg.ok}</p>}
      </form>
    </details>
  );
}

function Simulador({ id }) {
  const [erp, setErp] = useState("");
  const [coste, setCoste] = useState("");
  const [r, setR] = useState(null);
  const [error, setError] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const costeNum = costeDeTexto(coste);
  const simular = async (ev) => {
    ev.preventDefault();
    setTrabajando(true); setError(null);
    try { setR(await pedirCerebro("licitaciones/simulador", enviar({ motor_id: id, ...(erp.trim() ? { presupuesto_erp: erp.trim() } : { coste: costeNum }) }))); }
    catch (e) { if (e.status === 403 || e.status === 401) setR(null); setError(e); }
    finally { setTrabajando(false); }
  };
  if (error && (error.status === 403 || error.status === 401)) return null;      // para los demás grupos, la tarjeta no aparece
  const apt = aptitudSimulacion(r);
  return (
    <section className="tarjeta" aria-label="Simulador de ofertas">
      <h2>Simulador de ofertas</h2>
      <p className="meta">Con las adjudicaciones de concursos parecidos: con qué baja se ha ganado y qué probabilidad daría cada precio, <strong>suponiendo que gana la mejor oferta económica</strong>. Es una estimación orientativa de cálculo fijo (no de IA): el precio lo decide una persona.</p>
      <form className="lic-fila" onSubmit={simular}>
        <label>Tu coste estimado, sin IVA (€, opcional)
          <input type="text" inputMode="decimal" value={coste} onChange={(x) => setCoste(x.target.value)} placeholder="150.000" />
        </label>
        <label>…o el código de un presupuesto del ERP
          <input type="text" value={erp} onChange={(x) => setErp(x.target.value)} placeholder="SAL-QTN-2026-00012" maxLength={140} />
        </label>
        <button className="boton si" type="submit" disabled={trabajando || (coste.trim() !== "" && costeNum === null) || (erp.trim() !== "" && coste.trim() !== "")}>{trabajando ? "Simulando…" : "Simular"}</button>
        {erp.trim() !== "" && coste.trim() !== "" && <span className="ayuda">Indica el coste o el presupuesto del ERP, no los dos</span>}
        {coste.trim() !== "" && costeNum === null && <span className="ayuda">Escribe un importe positivo, p. ej. 150.000</span>}
      </form>
      {error && <p role="alert" className="lic-error">{mensajeSimulador(error.status, error.detalle)}</p>}
      <ReglasPrecio id={id} alGuardar={() => setR(null)} />
      {r && (
        <>
          <p className={`lic-etiqueta ${apt.apto ? "abierta" : "aviso"}`}>{apt.texto}</p>
          <p className="meta">{r.muestra.n} concursos parecidos ({r.muestra.mercado}{r.muestra.desde ? `, de ${r.muestra.desde} a ${r.muestra.hasta}` : ""}). Presupuesto base: {importeTexto({ valor: String(r.licitacion.presupuesto), moneda: "EUR" })}.
            {r.muestra.ofertas_medias != null ? ` Ofertas por concurso: ${r.muestra.ofertas_medias} de media.` : ""}</p>
          <p>Baja del ganador en esos concursos: mitad por debajo de <strong>{r.bajas.p50} %</strong>; el 25 % más ajustado, por debajo de {r.bajas.p25} %; el 25 % más agresivo, por encima de {r.bajas.p75} %.{r.bajas.con_baja_anormal_pct != null ? ` Fueron baja anormal el ${r.bajas.con_baja_anormal_pct} %.` : ""}</p>
          {r.coste_erp && <p className="meta">{costeErpTexto(r.coste_erp)}</p>}
          {r.avisos.map((a, i) => <p key={i} className="lic-error" role="note">{a}</p>)}
          {r.recomendacion
            ? <p><strong>Mejor margen esperado:</strong> baja del {r.recomendacion.baja_pct} % (precio {importeTexto({ valor: String(r.recomendacion.precio), moneda: "EUR" })}): probabilidad de ganar {probabilidadConRango(r.recomendacion)}, margen esperado {importeTexto({ valor: String(r.recomendacion.margen_esperado), moneda: "EUR" })}. <span className="meta">{r.motivo_recomendacion}</span></p>
            : <p className="meta">{r.motivo_recomendacion}</p>}
          <table className="lic-tabla">
            <thead><tr><th>Baja</th><th>Precio</th><th>Prob. de ganar (rango)</th><th>Riesgo baja anormal</th>{r.reglas && <th>Puntos de precio</th>}{r.coste != null && <th>Margen esperado</th>}</tr></thead>
            <tbody>
              {filasDeCurva(r).map((f) => (
                <tr key={f.baja_pct} className={r.recomendacion && f.baja_pct === r.recomendacion.baja_pct ? "lic-destacada" : ""}>
                  <td>{f.baja_pct} %</td><td>{importeTexto({ valor: String(f.precio), moneda: "EUR" })}</td><td>{probabilidadConRango(f)}</td><td>{f.p_anormal == null ? "sin datos" : porcentaje(f.p_anormal)}</td>
                  {r.reglas && <td>{f.puntos_precio == null ? "—" : `${String(f.puntos_precio).replace(".", ",")} de ${String(r.reglas.puntos_precio).replace(".", ",")}`}</td>}
                  {r.coste != null && <td>{importeTexto({ valor: String(f.margen_esperado), moneda: "EUR" })}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          <details className="lic-informe">
            <summary>Cómo se ha calculado y cuánto fiarse</summary>
            <ul>{r.supuestos.map((t, i) => <li key={i}>{t}</li>)}</ul>
            <p className="meta">Comprobación con el pasado: {r.backtest.error_calibracion == null ? r.backtest.motivo : `error medio de calibración ${porcentaje(r.backtest.error_calibracion)} con ${r.backtest.n} concursos${r.backtest.apto ? " (dentro de lo acordado)" : ` (${r.backtest.motivo})`}`}.</p>
            <p className="meta">{r.nota}</p>
          </details>
        </>
      )}
    </section>
  );
}

export default function Ficha() {
  const { id } = useParams();
  const [x, setX] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { pedir(`tenders/${encodeURIComponent(id)}`).then(setX).catch(setError); }, [id]);

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones/buscar">← Buscar licitaciones</Link></p>
      {error && <Fallo e={error} />}
      {!x && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {x && (
        <>
          <h1>{x.titulo || "(sin título)"}</h1>
          <Estudiar id={id} />
          <section className="tarjeta" aria-label="Resumen">
            <dl className="lic-ficha">
              <Dato t="Estado"><span className={`lic-etiqueta ${x.estado}`}>{estadoEtiqueta(x.estado)}</span>{x.estado_origen ? ` (en origen: ${x.estado_origen})` : ""}</Dato>
              <Dato t="Expediente">{x.expediente}</Dato>
              <Dato t="Comprador">{fichaOrgHref(x.comprador?.id) ? <Link href={fichaOrgHref(x.comprador.id)}>{x.comprador.nombre}</Link> : x.comprador?.nombre}{x.comprador?.nif ? ` · ${x.comprador.nif}` : ""}</Dato>
              <Dato t="Procedimiento">{x.procedimiento?.replace(/_/g, " ")}</Dato>
              <Dato t="Plazo de presentación">{x.plazos?.presentacion ? fechaTexto(x.plazos.presentacion) : null}</Dato>
              <Dato t="Última actualización">{fechaTexto(x.actualizada_en)}</Dato>
              <Dato t="CPV">{x.cpv?.join(", ")}</Dato>
              <Dato t="Zona (NUTS)">{x.nuts?.join(", ")}</Dato>
              <Dato t="Fuente">{(x.fuentes || []).map(nombreFuente).join(", ")}</Dato>
              <Dato t="Original">{x.url_origen ? <Enlace url={x.url_origen}>Ver en la plataforma</Enlace> : null}</Dato>
            </dl>
          </section>

          {x.importes?.length > 0 && (
            <section className="tarjeta" aria-label="Importes">
              <h2>Importes</h2>
              <ul>{x.importes.map((i, n) => <li key={n}>{importeTexto(i, true)}</li>)}</ul>
            </section>
          )}

          {x.lotes?.length > 0 && (
            <section className="tarjeta" aria-label="Lotes">
              <h2>Lotes</h2>
              <table className="lic-tabla">
                <thead><tr><th>Lote</th><th>Objeto</th><th>Importes</th></tr></thead>
                <tbody>{x.lotes.map((l) => (
                  <tr key={l.numero}><td>{l.numero}</td><td>{l.objeto || "—"}</td><td>{(l.importes || []).map((i) => importeTexto(i, true)).join(" · ") || "—"}</td></tr>
                ))}</tbody>
              </table>
            </section>
          )}

          {x.criterios?.length > 0 && (
            <section className="tarjeta" aria-label="Criterios de adjudicación">
              <h2>Criterios de adjudicación</h2>
              <ul>{x.criterios.map((c, n) => <li key={n}>{c.descripcion || "—"}{c.peso != null ? ` · ${c.peso} puntos` : ""} <span className="meta">({String(c.tipo).replace(/_/g, " ")})</span></li>)}</ul>
            </section>
          )}

          {x.adjudicaciones?.length > 0 && (
            <section className="tarjeta" aria-label="Adjudicaciones">
              <h2>Adjudicaciones</h2>
              <table className="lic-tabla">
                <thead><tr><th>Lote</th><th>Resultado</th><th>Adjudicatario</th><th>Importe</th><th>Baja</th><th>Ofertas</th></tr></thead>
                <tbody>{x.adjudicaciones.map((a) => (
                  <tr key={a.id}>
                    <td>{a.lote}</td><td>{a.resultado}</td>
                    <td>{fichaOrgHref(a.adjudicatario?.id) ? <Link href={fichaOrgHref(a.adjudicatario.id)}>{a.adjudicatario.nombre || "—"}</Link> : (a.adjudicatario?.nombre || "—")}{a.adjudicatario?.nif ? <span className="meta"> · {a.adjudicatario.nif}</span> : null}</td>
                    <td>{(a.importes || []).filter((i) => i.significado === "adjudicado").map((i) => importeTexto(i)).join(" · ") || "—"}</td>
                    <td>{typeof a.baja === "number" ? `${(a.baja * 100).toFixed(1).replace(".", ",")} %` : "—"}</td>
                    <td>{a.ofertas_recibidas ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </section>
          )}

          {x.documentos?.length > 0 && (
            <section className="tarjeta" aria-label="Documentos">
              <h2>Documentos</h2>
              <ul>{x.documentos.map((d, n) => <li key={n}><Enlace url={d.url_origen}>{d.nombre || d.url_origen}</Enlace> <span className="meta">{String(d.tipo || "").replace(/_/g, " ")}</span></li>)}</ul>
            </section>
          )}

          <Pliegos id={id} />
          <Simulador id={id} />
          <Oferta id={id} />
          <Parecidas id={id} />

          {x.evidencia && (
            <section className="tarjeta" aria-label="Evidencia">
              <h2>Evidencia</h2>
              <p className="meta">El original de esta ficha está guardado sin modificar. Su huella SHA-256 permite comprobar que no ha cambiado.</p>
              <dl className="lic-ficha">
                <Dato t="Fuente">{nombreFuente(x.evidencia.fuente)}</Dato>
                <Dato t="Visto por última vez">{fechaTexto(x.evidencia.capturado_en)}</Dato>
                <Dato t="Huella SHA-256"><code>{x.evidencia.sha256}</code></Dato>
                <Dato t="Versión de la ficha">{x.version_entidad}</Dato>
              </dl>
            </section>
          )}
        </>
      )}
    </div>
  );
}
