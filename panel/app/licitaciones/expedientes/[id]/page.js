"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CUMPLIMIENTOS, cumplimientoEtiqueta, cumplimientoNecesitaNota, estadoEtiqueta, estadoPliego, estadoRequisito, etiquetaEmbudo, fechaTexto, fichaOrgHref, importeTexto, lecturaPliego, lugarCita, matrizCsv, matrizDe, mensajeEmbudo, mensajePliegos, resumenMatriz, nombreFuente, puedeDescargarPliego, resumenRequisitos, tipoRequisito, urlSegura } from "../../../../lib/licitaciones";
import { Fallo, pedir, pedirCerebro } from "../../cliente";

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
